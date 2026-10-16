"""The decision engine: observations in, threat assessments and alert events out.

Pure and deterministic — time is always passed in, nothing is read from a clock,
network or database — so the same engine runs live in the server, on an edge node,
and inside the offline evaluation harness over thousands of simulated scenarios.

Per ``step(now)``:

1. **State update** — each observation updates its entity's Kalman filter and
   history (done at ingest).
2. **Association** — camera tracks are linked to cooperative GPS tags by spatial
   gating with hysteresis, and to RFID/BLE reads at fixed readers. A linked pair is
   one physical entity: the tag supplies identity, the camera supplies class and
   behaviour.
3. **Spoof checks** — a GPS tag inside camera coverage that no camera track
   corroborates accumulates suspicion.
4. **Assessment** — geofence state, behavioural features -> anomaly score,
   Kalman time-to-breach, identity and spoof suspicion become ``Evidence``;
   fusion gives a calibrated probability; scoring gives a level.
5. **Alerting** — the alert state machine turns levels into events, and a sweep
   reports entities that vanished while alerting.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from pids_core.alerts import AlertPolicy, AlertTracker
from pids_core.anomaly import AnomalyScorer
from pids_core.badges import BadgeLinker, Candidate
from pids_core.contracts import (
    AlertEvent,
    EntityClass,
    GeoPoint,
    GpsFix,
    TagKind,
    TagRead,
    ThreatAssessment,
    TrackBatch,
    Velocity,
    ZoneKind,
)
from pids_core.coverage import Coverage, sector
from pids_core.features import Sample, TrackFeatures, TrackHistory, extract
from pids_core.fusion import Evidence, FusionWeights, fuse
from pids_core.geo import Enu
from pids_core.kalman import KalmanCV
from pids_core.scoring import ScoreInput, ScoringPolicy, score
from pids_core.site import Site
from pids_core.spoofing import SpoofMonitor

# Unmodelled-acceleration spectral density (m^2/s^3) per class: walkers change
# velocity gently, vehicles brake and accelerate hard.
_ACCEL_PSD = {
    EntityClass.PERSON: 0.15,
    EntityClass.VEHICLE: 1.5,
    EntityClass.ANIMAL: 0.4,
    EntityClass.UNKNOWN: 0.4,
}
_GPS_ACCEL_PSD = {TagKind.PERSON: 0.3, TagKind.VEHICLE: 1.5, TagKind.ASSET: 0.3}
# A link is ambiguous unless the best candidate is clearly nearer than the next.
_AMBIGUITY_RATIO = 0.5
_TAG_TO_CLASS = {
    TagKind.PERSON: EntityClass.PERSON,
    TagKind.VEHICLE: EntityClass.VEHICLE,
    TagKind.ASSET: EntityClass.UNKNOWN,
}
_COMPATIBLE = {
    TagKind.PERSON: {EntityClass.PERSON, EntityClass.UNKNOWN},
    TagKind.VEHICLE: {EntityClass.VEHICLE, EntityClass.UNKNOWN},
    # Crated assets are invisible to cameras; never bind one to a passer-by.
    TagKind.ASSET: set(),
}
_CLASS_EMA = 0.3
_ANOMALY_REFRESH_S = 1.0
_STITCH_WINDOW_S = 4.0
_STITCH_GATE_M = 8.0
# A forecast breach only counts if the entity is closing on the boundary: the
# straight-line distance covered per second must be a real fraction of its speed.
_MIN_CLOSING_RATIO = 0.35
# Velocity from a brand-new track is mostly prior; do not forecast from it.
_FORECAST_MIN_AGE_S = 2.0


FeatureHook = Callable[[str, float, TrackFeatures], None]
"""Observer called with (entity_id, time, features) whenever features are computed."""


class EngineConfig:
    def __init__(
        self,
        fusion: FusionWeights | None = None,
        scoring: ScoringPolicy | None = None,
        alerts: AlertPolicy | None = None,
        forecast_horizon_s: float = 60.0,
        entity_ttl_s: float = 60.0,
        vision_fresh_s: float = 1.5,
        tag_fresh_s: float = 3.0,
    ) -> None:
        self.fusion = fusion or FusionWeights()
        self.scoring = scoring or ScoringPolicy()
        self.alerts = alerts or AlertPolicy()
        self.forecast_horizon_s = forecast_horizon_s
        self.entity_ttl_s = entity_ttl_s
        self.vision_fresh_s = vision_fresh_s
        self.tag_fresh_s = tag_fresh_s


@dataclass(slots=True)
class _Entity:
    entity_id: str
    kind: Literal["vision", "tag"]
    kf: KalmanCV
    history: TrackHistory
    last_t: float
    sigma_m: float
    source: str
    trace: dict[str, datetime] = field(default_factory=dict)
    # vision
    class_probs: dict[EntityClass, float] = field(default_factory=dict)
    first_t: float = 0.0
    thermal: bool | None = None
    edge_anomaly: float | None = None
    linked_tag: str | None = None
    rfid_tag: str | None = None
    badge_tag: str | None = None  # BLE badge, linked by RSSI-vs-motion evidence
    # tag
    tag_id: str | None = None
    tag_kind: TagKind = TagKind.PERSON
    spoof: SpoofMonitor | None = None
    linked_vision: str | None = None
    # cached behavioural score
    anomaly: float | None = None
    anomaly_t: float | None = None

    def entity_class(self) -> tuple[EntityClass, float]:
        if not self.class_probs:
            return EntityClass.UNKNOWN, 0.0
        cls = max(self.class_probs, key=lambda c: self.class_probs[c])
        return cls, self.class_probs[cls]


@dataclass(frozen=True, slots=True)
class StepResult:
    assessments: list[ThreatAssessment]
    events: list[AlertEvent]


class DecisionEngine:
    def __init__(
        self,
        site: Site,
        config: EngineConfig | None = None,
        anomaly_scorer: AnomalyScorer | None = None,
        on_features: FeatureHook | None = None,
        run_id: str | None = None,
    ) -> None:
        """``run_id`` namespaces alert ids so they stay unique across service restarts
        (entity ids such as tracker numbers restart from 1)."""
        self.site = site
        self.config = config or EngineConfig()
        self.scorer = anomaly_scorer
        self.on_features = on_features
        namespace = site.id if run_id is None else f"{site.id}@{run_id}"
        self.alerts = AlertTracker(policy=self.config.alerts, site_id=namespace)
        self._entities: dict[str, _Entity] = {}
        self._pending_reads: list[TagRead] = []
        self._linkers = {r.id: BadgeLinker() for r in site.config.readers if r.kind == "ble"}
        self._last_step_t: float | None = None
        self._tz = ZoneInfo(site.config.site.timezone)
        # Where a camera detects reliably (inner 70% of its range): only there does
        # *not* seeing a tagged person count as evidence against the tag.
        self._reliable_view = Coverage(
            {
                n.id: sector(n.position, n.heading_deg, n.fov_deg, 0.7 * n.range_m)
                for n in site.config.nodes
            }
        )

    # ------------------------------------------------------------------ ingest

    def ingest_tracks(self, batch: TrackBatch) -> None:
        t = batch.captured_at.timestamp()
        for tr in batch.tracks:
            eid = f"{batch.node_id}/{tr.track_id}"
            p = self.site.frame.to_enu(tr.position.lat, tr.position.lon)
            vel = (tr.velocity.east, tr.velocity.north) if tr.velocity else None
            ent = self._entities.get(eid)
            if ent is None:
                ent = _Entity(
                    entity_id=eid,
                    kind="vision",
                    kf=KalmanCV.initialise(
                        t, p.east, p.north, tr.position_sigma_m, vel, _ACCEL_PSD[tr.entity_class]
                    ),
                    history=TrackHistory(),
                    last_t=t,
                    first_t=t,
                    sigma_m=tr.position_sigma_m,
                    source=f"vision:{batch.node_id}",
                )
                self._stitch(ent, batch.node_id, t)
                self._entities[eid] = ent
            elif t > ent.last_t:
                ent.kf.update(t, p.east, p.north, tr.position_sigma_m)
            else:
                continue
            ent.last_t = t
            ent.sigma_m = tr.position_sigma_m
            ent.thermal = tr.thermal_confirmed
            ent.edge_anomaly = tr.anomaly_score
            ent.trace = dict(batch.trace)
            _update_class(ent, tr.entity_class, tr.class_confidence)
            self._record(ent, t)

    def _stitch(self, new: _Entity, node_id: str, t: float) -> None:
        """Carry identity across a tracker re-acquisition (motion-based, not appearance).

        When a camera loses a person for a few seconds the tracker starts a new ID.
        If a track on the same node ended moments ago where this one begins, the new
        track inherits its tag identity and class belief — otherwise a badge read at
        the gate would be forgotten the first time the guard walks behind a pillar.
        """
        best: tuple[float, _Entity] | None = None
        for old in self._entities.values():
            if (
                old.kind != "vision"
                or not old.source.endswith(node_id)
                or not 0.0 < t - old.last_t <= _STITCH_WINDOW_S
                or (old.rfid_tag is None and not old.class_probs)
            ):
                continue
            predicted = Enu(*old.kf.forecast(t - old.kf.t))
            d = predicted.distance_to(Enu(*new.kf.position))
            if d <= max(_STITCH_GATE_M, 3.0 * old.sigma_m) and (best is None or d < best[0]):
                best = (d, old)
        if best is not None:
            old = best[1]
            new.rfid_tag = old.rfid_tag
            for linker in self._linkers.values():
                for badge, owner in list(linker.links.items()):
                    if owner == old.entity_id:  # the badge follows the person
                        linker.links[badge] = new.entity_id
                        new.badge_tag, old.badge_tag = badge, None
            new.class_probs = dict(old.class_probs)
            new.first_t = old.first_t
            if old.linked_tag is not None:
                tag = self._entities.get(f"tag/{old.linked_tag}")
                if tag is not None and tag.linked_vision == old.entity_id:
                    tag.linked_vision = new.entity_id
                    new.linked_tag = old.linked_tag
                    old.linked_tag = None

    def ingest_gps(self, fix: GpsFix, received_at: datetime | None = None) -> None:
        t = fix.at.timestamp()
        recv = (received_at or fix.at).timestamp()
        eid = f"tag/{fix.tag_id}"
        p = self.site.frame.to_enu(fix.position.lat, fix.position.lon)
        tag_cfg = self.site.tags.get(fix.tag_id)
        kind = tag_cfg.kind if tag_cfg else TagKind.PERSON
        ent = self._entities.get(eid)
        if ent is None:
            ent = _Entity(
                entity_id=eid,
                kind="tag",
                kf=KalmanCV.initialise(
                    t, p.east, p.north, fix.accuracy_m, None, _GPS_ACCEL_PSD[kind]
                ),
                history=TrackHistory(),
                last_t=t,
                first_t=t,
                sigma_m=fix.accuracy_m,
                source=f"gps:{fix.tag_id}",
                tag_id=fix.tag_id,
                tag_kind=kind,
                spoof=SpoofMonitor(kind=kind),
            )
            self._entities[eid] = ent
        spoof = ent.spoof or SpoofMonitor(kind=kind)
        ent.spoof = spoof
        spoof.observe_fix(t, p.east, p.north, fix.accuracy_m, fix.hdop, recv)
        if t > ent.last_t:
            m2 = ent.kf.update(t, p.east, p.north, fix.accuracy_m)
            spoof.observe_innovation(m2, recv)
            ent.last_t = t
        ent.sigma_m = fix.accuracy_m
        ent.trace = dict(fix.trace)
        self._record(ent, t)

    def ingest_tag_read(self, read: TagRead) -> None:
        self._pending_reads.append(read)

    def _record(self, ent: _Entity, t: float) -> None:
        e, n = ent.kf.position
        hit = self.site.zones.locate(Enu(e, n))
        ent.history.append(Sample(t=t, east=e, north=n, zone_kind=hit.kind))

    # -------------------------------------------------------------------- step

    def step(self, now: datetime) -> StepResult:
        t = now.timestamp()
        dt = 0.0 if self._last_step_t is None else max(0.0, t - self._last_step_t)
        self._last_step_t = t

        self._associate(t)
        self._apply_tag_reads()
        self._link_badges(t)
        self._check_tags_against_vision(t, dt)

        local_hour = _local_hour(now, self._tz)
        assessments: list[ThreatAssessment] = []
        events: list[AlertEvent] = []
        for ent in list(self._entities.values()):
            if t - ent.last_t > self.config.alerts.lost_after_s:
                continue
            if ent.kind == "tag" and ent.linked_vision is not None:
                continue  # represented by the linked camera track
            a = self._assess(ent, now, t, local_hour)
            assessments.append(a)
            events.extend(self.alerts.update(a))

        events.extend(self.alerts.sweep(now))
        self._expire(t)
        return StepResult(assessments=assessments, events=events)

    # ------------------------------------------------------------- association

    def _fresh(self, kind: Literal["vision", "tag"], t: float) -> list[_Entity]:
        limit = self.config.vision_fresh_s if kind == "vision" else self.config.tag_fresh_s
        return [e for e in self._entities.values() if e.kind == kind and t - e.last_t <= limit]

    def _gate(self, v: _Entity, g: _Entity) -> float:
        # Position error of both sensors plus ~0.5 s of timing skew at current speed.
        return max(8.0, 3.0 * math.hypot(v.sigma_m, g.sigma_m) + 0.5 * v.kf.speed)

    def _alive(self, e: _Entity, t: float) -> bool:
        return t - e.last_t <= self.config.alerts.lost_after_s

    def _associate(self, t: float) -> None:
        # Keep existing links while both sides are alive and still agree (2x gate,
        # compared at positions predicted to now); freshness only gates *new* links,
        # so a camera missing a guard for a second does not strip their identity.
        for g in self._entities.values():
            if g.kind != "tag" or g.linked_vision is None:
                continue
            v = self._entities.get(g.linked_vision)
            if (
                v is None
                or not self._alive(v, t)
                or not self._alive(g, t)
                or _dist_at(v, g, t) > 2.0 * self._gate(v, g)
            ):
                if v is not None:
                    v.linked_tag = None
                g.linked_vision = None

        # New links: identity is granted only when it is unambiguous. A tag binds to
        # a camera track only if that track is the clear single candidate in the gate
        # and their motion agrees. If two people stand near one tag, nobody gets the
        # whitelist — an intruder must never inherit a guard's identity by walking
        # past them (recall first).
        vision = [v for v in self._fresh("vision", t) if v.linked_tag is None]
        for g in self._fresh("tag", t):
            if g.linked_vision is not None:
                continue
            in_gate = sorted(
                (_dist_at(v, g, t), v)
                for v in vision
                if v.entity_class()[0] in _COMPATIBLE[g.tag_kind]
                and _dist_at(v, g, t) <= self._gate(v, g)
                and _motion_agrees(v, g)
            )
            if not in_gate:
                continue
            if len(in_gate) > 1 and in_gate[0][0] > _AMBIGUITY_RATIO * in_gate[1][0]:
                continue
            v = in_gate[0][1]
            v.linked_tag = g.tag_id
            g.linked_vision = v.entity_id
            vision.remove(v)

    def _apply_tag_reads(self) -> None:
        reads, self._pending_reads = self._pending_reads, []
        for read in reads:
            reader = self.site.readers.get(read.reader_id)
            if reader is None:
                continue
            rt = read.at.timestamp()
            if reader.kind == "ble":
                rssi = read.rssi_dbm if read.rssi_dbm is not None else -70.0
                self._linkers[reader.id].hear(read.tag_id, rt, rssi)
                continue
            rp = Enu(*reader.position)
            best: tuple[float, _Entity] | None = None
            for v in self._entities.values():
                if v.kind != "vision" or abs(v.last_t - rt) > self.config.vision_fresh_s:
                    continue
                d = Enu(*v.kf.position).distance_to(rp)
                if d <= reader.range_m + 3.0 and (best is None or d < best[0]):
                    best = (d, v)
            if best is not None:
                best[1].rfid_tag = read.tag_id

    def _link_badges(self, t: float) -> None:
        """Give each BLE badge to the one person whose motion its signal follows, if any."""
        if not self._linkers:
            return
        linked: dict[str, str] = {}
        for reader_id, linker in self._linkers.items():
            reader = self.site.readers[reader_id]
            rp = Enu(*reader.position)
            candidates: list[Candidate] = []
            for v in self._entities.values():
                if v.kind != "vision" or not self._alive(v, t):
                    continue
                cls, _ = v.entity_class()
                if cls not in (EntityClass.PERSON, EntityClass.UNKNOWN):
                    continue  # badges are carried by people
                if Enu(*v.kf.position).distance_to(rp) > reader.range_m:
                    continue
                window = v.history.window(t, linker.policy.window_s)
                candidates.append(
                    Candidate(
                        v.entity_id,
                        [(s.t, Enu(s.east, s.north).distance_to(rp)) for s in window],
                    )
                )
            linker.update(t, candidates)
            linked.update({eid: tag for tag, eid in linker.links.items()})
        for v in self._entities.values():
            if v.kind == "vision":
                v.badge_tag = linked.get(v.entity_id)

    def _check_tags_against_vision(self, t: float, dt: float) -> None:
        if dt <= 0.0:
            return
        for g in self._fresh("tag", t):
            if g.spoof is None or g.tag_kind is TagKind.ASSET:
                continue
            in_view = self._reliable_view.covers(Enu(*g.kf.position))
            g.spoof.observe_vision(in_view, g.linked_vision is not None, dt, t)

    # -------------------------------------------------------------- assessment

    def _identity(self, ent: _Entity, t: float) -> tuple[str | None, bool, float, str | None]:
        """(tag_id, authorized, spoof_suspicion, home_zone) for an entity."""
        spoof = 0.0
        if ent.kind == "tag":
            tag_id = ent.tag_id
            spoof = ent.spoof.current(t) if ent.spoof else 0.0
        elif ent.linked_tag is not None:
            tag_id = ent.linked_tag
            g = self._entities.get(f"tag/{tag_id}")
            spoof = g.spoof.current(t) if g and g.spoof else 0.0
        else:
            tag_id = ent.badge_tag or ent.rfid_tag
        cfg = self.site.tags.get(tag_id) if tag_id else None
        authorized = bool(cfg and cfg.authorized)
        return tag_id, authorized, spoof, cfg.home_zone if cfg else None

    def _assess(self, ent: _Entity, now: datetime, t: float, local_hour: float) -> ThreatAssessment:
        zones = self.site.zones
        e, n = ent.kf.position
        pos = Enu(e, n)
        hit = zones.locate(pos)
        tag_id, authorized, spoof, home_zone = self._identity(ent, t)

        if ent.kind == "vision":
            cls, conf = ent.entity_class()
            ev_class: EntityClass | None = cls
            ev_conf: float | None = conf
            age: float | None = t - ent.first_t
            thermal = ent.thermal
        else:
            cls, ev_class, ev_conf, age, thermal = (
                _TAG_TO_CLASS[ent.tag_kind],
                None,
                None,
                None,
                None,
            )

        anomaly = ent.edge_anomaly
        if anomaly is None and (self.scorer is not None or self.on_features is not None):
            anomaly = self._anomaly(ent, t, local_hour)

        ttb: float | None = None
        predicted_zone: str | None = None
        velocity = ent.kf.velocity
        speed = ent.kf.speed
        settled = t - ent.first_t >= _FORECAST_MIN_AGE_S
        precise = ent.kf.velocity_sigma < max(0.8, 0.5 * speed)
        if hit.kind is not ZoneKind.CRITICAL and settled and precise:
            entry = zones.predict_entry(
                ZoneKind.CRITICAL, pos, velocity, self.config.forecast_horizon_s
            )
            if entry is not None and entry.seconds > 0:
                gap = max(zones.distance_to_kind(ZoneKind.CRITICAL, pos), 0.0)
                if gap / entry.seconds >= _MIN_CLOSING_RATIO * speed:
                    ttb, predicted_zone = entry.seconds, entry.zone.id

        containment_breach = home_zone is not None and not zones.contains(home_zone, pos)

        fused = fuse(
            Evidence(
                zone_kind=hit.kind,
                entity_class=ev_class,
                class_confidence=ev_conf,
                track_age_s=age,
                thermal_confirmed=thermal,
                anomaly_score=anomaly,
                time_to_breach_s=ttb,
                authorized_tag=authorized,
                spoof_suspicion=spoof,
            ),
            self.config.fusion,
        )
        s = score(
            ScoreInput(
                probability=fused.probability,
                zone_kind=hit.kind,
                entity_class=ev_class,
                class_confidence=ev_conf,
                track_age_s=age,
                authorized=authorized,
                spoof_suspicion=spoof,
                time_to_breach_s=ttb,
                containment_breach=containment_breach,
            ),
            self.config.scoring,
        )
        flags = list(s.flags)
        if tag_id is not None and tag_id not in self.site.tags:
            flags.append("UNKNOWN_TAG")

        lat, lon = self.site.frame.to_wgs84(pos)
        sources = [ent.source]
        if ent.linked_tag:
            sources.append(f"gps:{ent.linked_tag}")
        if ent.rfid_tag:
            sources.append(f"rfid:{ent.rfid_tag}")
        if ent.badge_tag:
            sources.append(f"ble:{ent.badge_tag}")
        return ThreatAssessment(
            site_id=self.site.id,
            entity_id=ent.entity_id,
            at=now,
            entity_class=cls,
            position=GeoPoint(lat=lat, lon=lon),
            velocity=Velocity(east=velocity[0], north=velocity[1]),
            zone_id=hit.zone.id if hit.zone else None,
            zone_kind=hit.kind,
            probability=fused.probability,
            score=s.score,
            level=s.level,
            contributions=list(fused.contributions),
            tag_id=tag_id,
            authorized=authorized,
            spoof_suspicion=spoof,
            anomaly_score=anomaly,
            time_to_breach_s=ttb,
            predicted_zone_id=predicted_zone,
            flags=flags,
            sources=sources,
            trace={**ent.trace, "decided": now},
        )

    def _anomaly(self, ent: _Entity, t: float, local_hour: float) -> float | None:
        """Behavioural anomaly score, refreshed at most once per ``_ANOMALY_REFRESH_S``.

        The features summarise a 30-second window, so re-scoring every frame adds
        cost without information.
        """
        if ent.anomaly_t is not None and t - ent.anomaly_t < _ANOMALY_REFRESH_S:
            return ent.anomaly
        features = extract(ent.history, self.site.zones, t, local_hour)
        if features is not None and self.on_features is not None:
            self.on_features(ent.entity_id, t, features)
        ent.anomaly = (
            float(self.scorer.score(features))
            if features is not None and self.scorer is not None
            else None
        )
        ent.anomaly_t = t
        return ent.anomaly

    def _expire(self, t: float) -> None:
        for eid in [
            eid for eid, e in self._entities.items() if t - e.last_t > self.config.entity_ttl_s
        ]:
            ent = self._entities.pop(eid)
            if ent.linked_tag is not None:
                g = self._entities.get(f"tag/{ent.linked_tag}")
                if g is not None:
                    g.linked_vision = None
            if ent.linked_vision is not None:
                v = self._entities.get(ent.linked_vision)
                if v is not None:
                    v.linked_tag = None
            # The persisted alert stays open for the operator; the state machine
            # forgets the entity so a later track reusing this id (edge node
            # restarts reuse tracker ids) starts a fresh episode.
            self.alerts.forget(eid)


def _update_class(ent: _Entity, cls: EntityClass, conf: float) -> None:
    """Exponential smoothing of the class distribution across frames.

    A single-frame misclassification (a dog briefly labelled "person") shifts the
    track's class only if it persists, which removes a major nuisance-alarm source.
    """
    others = [c for c in EntityClass if c is not cls]
    target = {cls: conf, **{c: (1.0 - conf) / len(others) for c in others}}
    if not ent.class_probs:
        ent.class_probs = target
        return
    for c in EntityClass:
        ent.class_probs[c] = (1 - _CLASS_EMA) * ent.class_probs.get(c, 0.0) + _CLASS_EMA * target[c]


def _motion_agrees(v: _Entity, g: _Entity) -> bool:
    """Both stationary, or moving in a similar direction at a similar speed."""
    sv, sg = v.kf.speed, g.kf.speed
    if sv < 0.6 or sg < 0.6:
        return abs(sv - sg) < 1.5
    ve, vn = v.kf.velocity
    ge, gn = g.kf.velocity
    cos = (ve * ge + vn * gn) / (sv * sg)
    return cos > 0.7 and 0.5 < sv / sg < 2.0


def _dist_at(a: _Entity, b: _Entity, t: float) -> float:
    """Distance between two entities with both filters extrapolated to time ``t``."""
    pa = Enu(*a.kf.forecast(max(t - a.kf.t, 0.0)))
    pb = Enu(*b.kf.forecast(max(t - b.kf.t, 0.0)))
    return pa.distance_to(pb)


def _local_hour(now: datetime, tz: ZoneInfo) -> float:
    local = now.astimezone(tz)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


class DecisionModel(BaseModel):
    """A versioned operating point: fusion weights + scoring thresholds, as one file.

    Weights and thresholds are only meaningful together (a threshold is chosen for
    a particular calibration), so they are shipped and loaded as a unit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fusion: FusionWeights = Field(default_factory=FusionWeights)
    scoring: ScoringPolicy = Field(default_factory=ScoringPolicy)
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path) -> DecisionModel:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def engine_config(self, **overrides: Any) -> EngineConfig:
        return EngineConfig(fusion=self.fusion, scoring=self.scoring, **overrides)
