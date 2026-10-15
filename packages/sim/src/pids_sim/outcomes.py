"""Score one run against ground truth.

* A **threat agent is detected** if any alert attributed to it reaches WARNING or
  above before the scenario ends. **Lead time** is breach time minus first alert
  time (positive = warned before the breach).
* A **nuisance alarm** is a RAISED alert attributed to a non-threat agent or to a
  ghost track (no agent at all). Escalations of an already-raised alert are not
  counted again — an operator experiences one alarm per raise.
"""

from __future__ import annotations

from dataclasses import dataclass

from pids_core.contracts import AlertEventKind, ThreatLevel
from pids_sim.runner import RunResult


@dataclass(frozen=True, slots=True)
class ThreatOutcome:
    agent_id: str
    role: str
    detected: bool
    first_alert_t: float | None
    breach_t: float | None
    lead_time_s: float | None
    critical: bool


@dataclass(frozen=True, slots=True)
class RunOutcome:
    family: str
    seed: int
    duration_s: float
    threats: list[ThreatOutcome]
    nuisance_alarms: int
    nuisance_by_role: dict[str, int]


def score_run(r: RunResult) -> RunOutcome:
    first_alert: dict[str, float] = {}
    critical: set[str] = set()
    nuisance = 0
    by_role: dict[str, int] = {}
    for ev in r.events:
        if ev.kind not in (AlertEventKind.RAISED, AlertEventKind.ESCALATED):
            continue
        agent = r.agent_of(ev.assessment.entity_id)
        truth = r.truth.get(agent) if agent else None
        if truth is not None and truth.is_threat:
            t = r.seconds(ev.at)
            first_alert.setdefault(truth.agent_id, t)
            if ev.level is ThreatLevel.CRITICAL:
                critical.add(truth.agent_id)
        elif ev.kind is AlertEventKind.RAISED:
            nuisance += 1
            role = truth.role.value if truth else "ghost"
            by_role[role] = by_role.get(role, 0) + 1

    threats = []
    for truth in r.truth.values():
        if not truth.is_threat:
            continue
        first = first_alert.get(truth.agent_id)
        breach = truth.breach_t if truth.breach_t is not None else truth.containment_breach_t
        threats.append(
            ThreatOutcome(
                agent_id=truth.agent_id,
                role=truth.role.value,
                detected=first is not None,
                first_alert_t=first,
                breach_t=breach,
                lead_time_s=(breach - first) if first is not None and breach is not None else None,
                critical=truth.agent_id in critical,
            )
        )
    return RunOutcome(
        family=r.spec.family.value,
        seed=r.spec.seed,
        duration_s=r.spec.duration_s,
        threats=threats,
        nuisance_alarms=nuisance,
        nuisance_by_role=by_role,
    )
