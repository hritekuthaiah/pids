"""Alert state machine (PLT-05).

Per entity, turns a stream of threat levels into a small number of meaningful
alert events:

* **RAISED** — the level reaches the alerting threshold (WARNING by default).
* **ESCALATED** — the level rises above the active alert's level. Escalation is
  *never* debounced: WARNING -> CRITICAL fires the moment it happens.
* repeats at the same or a lower level are silent — one vehicle idling on a
  boundary does not raise the same WARNING every second and bury a real breach.
* **CLEARED** — the level has stayed below the threshold for ``clear_hold_s``
  (hysteresis, so a contact flickering across a threshold does not flap).
* **TRACK_LOST** — the entity stopped reporting while an alert was active. This is
  *not* a clear: an intruder who vanished from view inside the compound is still
  there. The alert stays open for the operator; the server decides when to close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from pids_core.contracts import AlertEvent, AlertEventKind, ThreatAssessment, ThreatLevel


class AlertPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raise_at: ThreatLevel = ThreatLevel.WARNING
    clear_hold_s: float = 20.0
    lost_after_s: float = 6.0


@dataclass(slots=True)
class _Active:
    alert_id: str
    level: ThreatLevel
    below_since: float | None = None
    lost: bool = False


@dataclass(slots=True)
class AlertTracker:
    policy: AlertPolicy
    site_id: str
    _active: dict[str, _Active] = field(default_factory=dict)
    _seq: dict[str, int] = field(default_factory=dict)
    _last: dict[str, ThreatAssessment] = field(default_factory=dict)
    _last_seen: dict[str, float] = field(default_factory=dict)

    def _new_id(self, entity_id: str) -> str:
        n = self._seq.get(entity_id, 0) + 1
        self._seq[entity_id] = n
        return f"{self.site_id}/{entity_id}/{n}"

    def active(self, entity_id: str) -> ThreatLevel | None:
        a = self._active.get(entity_id)
        return a.level if a else None

    def update(self, a: ThreatAssessment) -> list[AlertEvent]:
        now = a.at.timestamp()
        eid = a.entity_id
        self._last[eid] = a
        self._last_seen[eid] = now
        active = self._active.get(eid)

        if active is None:
            if a.level >= self.policy.raise_at:
                alert_id = self._new_id(eid)
                self._active[eid] = _Active(alert_id=alert_id, level=a.level)
                return [_event(alert_id, AlertEventKind.RAISED, a, None, _reason(a))]
            return []

        active.lost = False
        if a.level > active.level:
            previous = active.level
            active.level = a.level
            active.below_since = None
            return [_event(active.alert_id, AlertEventKind.ESCALATED, a, previous, _reason(a))]

        if a.level >= self.policy.raise_at:
            active.below_since = None
            return []

        if active.below_since is None:
            active.below_since = now
        if now - active.below_since >= self.policy.clear_hold_s:
            del self._active[eid]
            return [
                _event(
                    active.alert_id,
                    AlertEventKind.CLEARED,
                    a,
                    active.level,
                    f"below {self.policy.raise_at.value} for {self.policy.clear_hold_s:.0f}s",
                )
            ]
        return []

    def sweep(self, now: datetime) -> list[AlertEvent]:
        """Emit TRACK_LOST once for active alerts whose entity stopped reporting."""
        t = now.timestamp()
        events = []
        for eid, active in self._active.items():
            seen = self._last_seen.get(eid, t)
            if not active.lost and t - seen >= self.policy.lost_after_s:
                active.lost = True
                last = self._last[eid]
                events.append(
                    _event(
                        active.alert_id,
                        AlertEventKind.TRACK_LOST,
                        last.model_copy(update={"at": now}),
                        active.level,
                        f"no observations for {t - seen:.0f}s — last seen in "
                        f"{last.zone_id or 'open ground'}",
                    )
                )
        return events

    def forget(self, entity_id: str) -> None:
        """Drop all state for an entity (after the server has closed its alert)."""
        for d in (self._active, self._last, self._last_seen):
            d.pop(entity_id, None)


def _reason(a: ThreatAssessment) -> str:
    where = a.zone_id or "open ground"
    flags = f" [{', '.join(a.flags)}]" if a.flags else ""
    return f"{a.entity_class.value} in {where}, threat {a.score}/100{flags}"


def _event(
    alert_id: str,
    kind: AlertEventKind,
    a: ThreatAssessment,
    previous: ThreatLevel | None,
    reason: str,
) -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id,
        kind=kind,
        level=a.level,
        previous_level=previous,
        at=a.at.astimezone(UTC),
        reason=reason,
        assessment=a,
    )
