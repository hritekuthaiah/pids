"""Threat scoring and graded severity (AIL-05).

Turns the fused probability, together with geometry and identity, into one of
four levels. The policy is deliberately asymmetric because a missed intruder is
the worst failure the system can make:

* Thresholds sit low (recall-biased); fusion, not a high threshold, is what keeps
  the nuisance-alarm rate down.
* **CRITICAL requires a geometric breach** of a critical (or containment) zone.
  Probabilistic sensors can push the fused score high while an entity is still in
  the outer ring; calling that CRITICAL would claim a breach the geometry does
  not support. Outside the core, a strong contact tops out at WARNING — which
  still dispatches a guard.
* **Recall floor.** A learned fusion model must never silently suppress a real
  breach: an untagged, persistent person/vehicle track inside a critical zone is
  never rated below WARNING, whatever the model says.
* **Predicted breach.** An entity forecast to enter a critical zone soon is raised
  to WARNING early — the point of trajectory prediction is lead time.
* **Containment.** A tagged asset outside its home zone is CRITICAL regardless of
  fusion: the event is the asset leaving, not anyone's behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from pids_core.contracts import EntityClass, ThreatLevel, ZoneKind


class ScoringPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    elevated_at: float = 0.25
    warning_at: float = 0.50
    critical_at: float = 0.50
    predicted_breach_horizon_s: float = 30.0
    floor_min_confidence: float = 0.45
    floor_min_age_s: float = 3.0


@dataclass(frozen=True, slots=True)
class ScoreInput:
    probability: float
    zone_kind: ZoneKind | None
    entity_class: EntityClass | None
    class_confidence: float | None
    track_age_s: float | None
    authorized: bool
    spoof_suspicion: float
    time_to_breach_s: float | None
    containment_breach: bool


@dataclass(frozen=True, slots=True)
class Score:
    level: ThreatLevel
    score: int
    flags: tuple[str, ...]


def score(inp: ScoreInput, policy: ScoringPolicy) -> Score:
    p = inp.probability
    flags: list[str] = []

    if p >= policy.warning_at:
        level = ThreatLevel.WARNING
    elif p >= policy.elevated_at:
        level = ThreatLevel.ELEVATED
    else:
        level = ThreatLevel.NOMINAL

    in_critical = inp.zone_kind is ZoneKind.CRITICAL
    if in_critical:
        flags.append("CRITICAL_ZONE_BREACH")
        if p >= policy.critical_at:
            level = ThreatLevel.CRITICAL

    trusted_tag = inp.authorized and inp.spoof_suspicion < 0.5
    if (
        in_critical
        and not trusted_tag
        and inp.entity_class in (EntityClass.PERSON, EntityClass.VEHICLE)
        and (inp.class_confidence or 0.0) >= policy.floor_min_confidence
        and (inp.track_age_s or 0.0) >= policy.floor_min_age_s
        and level < ThreatLevel.WARNING
    ):
        level = ThreatLevel.WARNING
        flags.append("RECALL_FLOOR")

    if (
        not in_critical
        and inp.time_to_breach_s is not None
        and inp.time_to_breach_s <= policy.predicted_breach_horizon_s
        and p >= policy.elevated_at
    ):
        flags.append("PREDICTED_BREACH")
        level = max(level, ThreatLevel.WARNING)

    if inp.containment_breach:
        flags.append("CONTAINMENT_BREACH")
        level = ThreatLevel.CRITICAL

    if inp.authorized:
        flags.append("AUTHORIZED_TAG")
    if inp.spoof_suspicion >= 0.5:
        flags.append("SPOOF_SUSPECTED")

    return Score(level=level, score=round(100 * p), flags=tuple(flags))
