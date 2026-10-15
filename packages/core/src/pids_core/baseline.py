"""Naive geofencing baselines — what PIDS is measured against (PLT-11).

Two baselines, both deliberately honest rather than straw men:

* ``gps-only`` — **traditional GPS geofencing.** Only devices that report GPS
  exist; an alarm fires when a non-whitelisted device is inside a zone, and when a
  tagged asset leaves its containment zone. It cannot see an intruder who carries
  no device, which is exactly the gap the paper motivates.
* ``line-crossing`` — **naive geofencing over the same detections PIDS gets.** Every
  camera track inside a zone alarms (warning ring -> WARNING, critical core ->
  CRITICAL) regardless of class, behaviour or corroboration; GPS devices are
  whitelisted by ID with no spoof checks.

Both use the same alert state machine as PIDS, so differences in alarm counts come
from the decision logic, not from debouncing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pids_core.alerts import AlertPolicy, AlertTracker
from pids_core.contracts import (
    AlertEvent,
    EntityClass,
    GeoPoint,
    GpsFix,
    TagRead,
    ThreatAssessment,
    ThreatLevel,
    TrackBatch,
    ZoneKind,
)
from pids_core.engine import StepResult
from pids_core.geo import Enu
from pids_core.site import Site

BaselineMode = Literal["gps-only", "line-crossing"]


@dataclass(slots=True)
class _Seen:
    position: GeoPoint
    t: float
    entity_class: EntityClass
    tag_id: str | None


class NaiveGeofence:
    def __init__(self, site: Site, mode: BaselineMode, alerts: AlertPolicy | None = None) -> None:
        self.site = site
        self.mode = mode
        self.alerts = AlertTracker(policy=alerts or AlertPolicy(), site_id=site.id)
        self._seen: dict[str, _Seen] = {}

    def ingest_tracks(self, batch: TrackBatch) -> None:
        if self.mode == "gps-only":
            return
        t = batch.captured_at.timestamp()
        for tr in batch.tracks:
            self._seen[f"{batch.node_id}/{tr.track_id}"] = _Seen(
                tr.position, t, tr.entity_class, None
            )

    def ingest_gps(self, fix: GpsFix, received_at: datetime | None = None) -> None:
        del received_at
        self._seen[f"tag/{fix.tag_id}"] = _Seen(
            fix.position, fix.at.timestamp(), EntityClass.UNKNOWN, fix.tag_id
        )

    def ingest_tag_read(self, read: TagRead) -> None:
        del read  # naive geofencing has no notion of proximity identity

    def step(self, now: datetime) -> StepResult:
        t = now.timestamp()
        assessments: list[ThreatAssessment] = []
        events: list[AlertEvent] = []
        for eid, seen in list(self._seen.items()):
            if t - seen.t > self.alerts.policy.lost_after_s:
                if t - seen.t > 60.0 and self.alerts.active(eid) is None:
                    del self._seen[eid]
                continue
            a = self._assess(eid, seen, now)
            assessments.append(a)
            events.extend(self.alerts.update(a))
        events.extend(self.alerts.sweep(now))
        return StepResult(assessments=assessments, events=events)

    def _assess(self, eid: str, seen: _Seen, now: datetime) -> ThreatAssessment:
        p = self.site.frame.to_enu(seen.position.lat, seen.position.lon)
        hit = self.site.zones.locate(p)
        tag = self.site.tags.get(seen.tag_id) if seen.tag_id else None
        whitelisted = bool(tag and tag.authorized)

        level = ThreatLevel.NOMINAL
        if not whitelisted:
            if hit.kind is ZoneKind.CRITICAL:
                level = ThreatLevel.CRITICAL
            elif hit.kind is ZoneKind.WARNING:
                level = ThreatLevel.WARNING
        flags: list[str] = []
        if (
            tag
            and tag.home_zone
            and not self.site.zones.contains(tag.home_zone, Enu(p.east, p.north))
        ):
            level = ThreatLevel.CRITICAL
            flags.append("CONTAINMENT_BREACH")

        prob = {ThreatLevel.CRITICAL: 1.0, ThreatLevel.WARNING: 0.6}.get(level, 0.0)
        return ThreatAssessment(
            site_id=self.site.id,
            entity_id=eid,
            at=now,
            entity_class=seen.entity_class,
            position=seen.position,
            velocity=None,
            zone_id=hit.zone.id if hit.zone else None,
            zone_kind=hit.kind,
            probability=prob,
            score=round(100 * prob),
            level=level,
            contributions=[],
            tag_id=seen.tag_id,
            authorized=whitelisted,
            flags=flags,
            sources=[f"baseline:{self.mode}"],
        )
