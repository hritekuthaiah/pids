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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pids_core.alerts import AlertPolicy, AlertTracker
from pids_core.anomaly import AnomalyScorer
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
from pids_core.features import Sample, TrackHistory, extract
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
_GPS_ACCEL_PSD = 0.3
_TAG_TO_CLASS = {
    TagKind.PERSON: EntityClass.PERSON,
    TagKind.VEHICLE: EntityClass.VEHICLE,
    TagKind.ASSET: EntityClass.UNKNOWN,
}
_COMPATIBLE = {
    TagKind.PERSON: {EntityClass.PERSON, EntityClass.UNKNOWN},
    TagKind.VEHICLE: {EntityClass.VEHICLE, EntityClass.UNKNOWN},
    TagKind.ASSET: set(EntityClass),
}
_CLASS_EMA = 0.3


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
    hits: int = 0
    thermal: bool | None = None
    edge_anomaly: float | None = None
    linked_tag: str | None = None
    rfid_tag: str | None = None
    # tag
    tag_id: str | None = None
    tag_kind: TagKind = TagKind.PERSON
    spoof: SpoofMonitor | None = None
    linked_vision: str | None = None

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
    ) -> None:
        self.site = site
        self.config = config or EngineConfig()
        self.scorer = anomaly_scorer
        self.alerts = AlertTracker(policy=self.config.alerts, site_id=site.id)
        self._entities: dict[str, _Entity] = {}
        self._pending_reads: list[TagRead] = []
        self._last_step_t: float | None = None
        self._tz = ZoneInfo(site.config.site.timezone)
        self._coverage = Coverage(
            {
                n.id: sector(n.position, n.heading_deg, n.fov_deg, n.range_m)
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
                    sigma_m=tr.position_sigma_m,
                    source=f"vision:{batch.node_id}",
                )
                self._entities[eid] = ent
            elif t > ent.last_t:
                ent.kf.update(t, p.east, p.north, tr.position_sigma_m)
            else:
                continue
            ent.last_t = t
            ent.sigma_m = tr.position_sigma_m
            ent.hits = tr.hits
            ent.thermal = tr.thermal_confirmed
            ent.edge_anomaly = tr.anomaly_score
            ent.trace = dict(batch.trace)
            _update_class(ent, tr.entity_class, tr.class_confidence)
            self._record(ent, t)

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
                kf=KalmanCV.initialise(t, p.east, p.north, fix.accuracy_m, None, _GPS_ACCEL_PSD),
                history=TrackHistory(),
                last_t=t,
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
        return max(8.0, 3.0 * math.hypot(v.sigma_m, g.sigma_m))

    def _associate(self, t: float) -> None:
        vision = {e.entity_id: e for e in self._fresh("vision", t)}
        tags = {e.entity_id: e for e in self._fresh("tag", t)}

        # Break stale or stretched links (hysteresis: 2x gate to keep, 1x to make).
        for g in self._entities.values():
            if g.kind != "tag" or g.linked_vision is None:
                continue
            v_linked = vision.get(g.linked_vision)
            if (
                g.entity_id not in tags
                or v_linked is None
                or _dist(v_linked, g) > 2.0 * self._gate(v_linked, g)
            ):
                stale = self._entities.get(g.linked_vision)
                if stale is not None:
                    stale.linked_tag = None
                g.linked_vision = None

        candidates = []
        for g in tags.values():
            if g.linked_vision is not None:
                continue
            for v in vision.values():
                if v.linked_tag is not None:
                    continue
                cls, _ = v.entity_class()
                if cls not in _COMPATIBLE[g.tag_kind]:
                    continue
                d = _dist(v, g)
                if d <= self._gate(v, g):
                    candidates.append((d, v.entity_id, g.entity_id))
        for _, vid, gid in sorted(candidates):
            v, g = self._entities[vid], self._entities[gid]
            if v.linked_tag is None and g.linked_vision is None:
                v.linked_tag = g.tag_id
                g.linked_vision = vid

    def _apply_tag_reads(self) -> None:
        reads, self._pending_reads = self._pending_reads, []
        for read in reads:
            reader = self.site.readers.get(read.reader_id)
            if reader is None:
                continue
            rt = read.at.timestamp()
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

    def _check_tags_against_vision(self, t: float, dt: float) -> None:
        if dt <= 0.0:
            return
        for g in self._fresh("tag", t):
            if g.spoof is None:
                continue
            in_view = self._coverage.covers(Enu(*g.kf.position))
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
            tag_id = ent.rfid_tag
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
            hits: int | None = ent.hits
            thermal = ent.thermal
        else:
            cls, ev_class, ev_conf, hits, thermal = (
                _TAG_TO_CLASS[ent.tag_kind],
                None,
                None,
                None,
                None,
            )

        features = extract(ent.history, zones, t, local_hour)
        anomaly = ent.edge_anomaly
        if anomaly is None and self.scorer is not None and features is not None:
            anomaly = float(self.scorer.score(features))

        ttb: float | None = None
        predicted_zone: str | None = None
        velocity = ent.kf.velocity
        speed = ent.kf.speed
        if hit.kind is not ZoneKind.CRITICAL and ent.kf.velocity_sigma < max(0.6, 0.5 * speed):
            entry = zones.predict_entry(
                ZoneKind.CRITICAL, pos, velocity, self.config.forecast_horizon_s
            )
            if entry is not None:
                ttb, predicted_zone = entry.seconds, entry.zone.id

        containment_breach = home_zone is not None and not zones.contains(home_zone, pos)

        fused = fuse(
            Evidence(
                zone_kind=hit.kind,
                entity_class=ev_class,
                class_confidence=ev_conf,
                hits=hits,
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
                hits=hits,
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
            if self.alerts.active(eid) is None:
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


def _dist(a: _Entity, b: _Entity) -> float:
    return Enu(*a.kf.position).distance_to(Enu(*b.kf.position))


def _local_hour(now: datetime, tz: ZoneInfo) -> float:
    local = now.astimezone(tz)
    return local.hour + local.minute / 60.0 + local.second / 3600.0
