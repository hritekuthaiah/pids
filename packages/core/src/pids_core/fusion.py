"""Decision-level sensor fusion -> one calibrated threat probability (AIL-09).

Method: log-odds evidence accumulation (a logistic model).

    logit P(threat | evidence) = bias + sum_k  w_k * term_k(evidence)

Each independent channel — geofence state, vision class/confidence, track
persistence, thermal confirmation, behavioural anomaly, predicted breach,
cooperative-tag identity, spoofing suspicion — contributes an additive amount of
log-odds. This is the naive-Bayes view of fusion: under conditional independence
each channel multiplies the odds by its likelihood ratio, so

* **corroboration is the mechanism.** One loud channel moves the odds by one
  factor; three agreeing independent channels multiply. Recall-biased detectors
  upstream can afford to be sensitive because a lone marginal detection cannot
  escalate on its own.
* **missing is not negative.** A channel that is unavailable (no thermal
  coverage, no anomaly model yet, no tag seen) contributes exactly zero — it
  neither raises nor lowers the threat. Absence of heat *within* thermal coverage
  is different: that is evidence, and it has its own term.
* **it is explainable.** Every alert carries each channel's log-odds
  contribution, which the dashboard renders as "why".
* **it is calibratable.** Because the model is logistic in fixed evidence terms,
  the weights can be fitted by maximum likelihood on labelled simulation
  (``pids_ml``) and reported with a reliability diagram / ECE. The defaults
  below are expert priors used until a fitted weight file is supplied.

Independence is an approximation (vision and thermal both respond to a warm
person), so a single ``corroboration`` interaction term lets the fitted model
correct for under- or over-counting when several channels agree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pids_core.contracts import ChannelContribution, EntityClass, ZoneKind

TERMS: tuple[str, ...] = (
    "zone_warning",
    "zone_critical",
    "class_person",
    "class_vehicle",
    "class_animal",
    "persistence",
    "thermal_present",
    "thermal_absent",
    "anomaly",
    "imminence",
    "authorized_tag",
    "spoof",
    "corroboration",
)

IMMINENCE_TAU_S = 30.0


@dataclass(frozen=True, slots=True)
class Evidence:
    """Raw evidence about one entity. ``None`` means the channel is unavailable."""

    zone_kind: ZoneKind | None
    entity_class: EntityClass | None
    class_confidence: float | None
    hits: int | None
    thermal_confirmed: bool | None
    anomaly_score: float | None
    time_to_breach_s: float | None
    authorized_tag: bool
    spoof_suspicion: float


class FusionWeights(BaseModel):
    """Log-odds weights for each evidence term (JSON-serialisable, fitted by pids_ml)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["expert-prior", "fitted"] = "expert-prior"
    version: str = "prior-1"
    bias: float = -4.0
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "zone_warning": 1.5,
            "zone_critical": 3.5,
            "class_person": 1.8,
            "class_vehicle": 1.5,
            "class_animal": -3.0,
            "persistence": 0.8,
            "thermal_present": 1.0,
            "thermal_absent": -0.8,
            "anomaly": 2.0,
            "imminence": 2.0,
            "authorized_tag": -5.0,
            "spoof": 4.0,
            "corroboration": 1.0,
        }
    )

    @model_validator(mode="after")
    def _all_terms_weighted(self) -> FusionWeights:
        unknown = set(self.weights) - set(TERMS)
        missing = set(TERMS) - set(self.weights)
        if unknown or missing:
            raise ValueError(f"fusion weights mismatch: unknown={unknown} missing={missing}")
        return self


@dataclass(frozen=True, slots=True)
class FusionResult:
    probability: float
    logit: float
    contributions: tuple[ChannelContribution, ...]


def terms(ev: Evidence) -> dict[str, float | None]:
    """Map raw evidence to the fixed feature terms of the logistic model.

    Returns ``None`` for terms whose channel is unavailable; they contribute 0.
    The exact same function is used when fitting weights, so training and
    inference cannot drift apart.
    """
    t: dict[str, float | None] = dict.fromkeys(TERMS)

    t["zone_warning"] = 1.0 if ev.zone_kind is ZoneKind.WARNING else 0.0
    t["zone_critical"] = 1.0 if ev.zone_kind is ZoneKind.CRITICAL else 0.0

    if ev.entity_class is not None and ev.class_confidence is not None:
        conf = min(max(ev.class_confidence, 0.0), 1.0)
        t["class_person"] = conf if ev.entity_class is EntityClass.PERSON else 0.0
        t["class_vehicle"] = conf if ev.entity_class is EntityClass.VEHICLE else 0.0
        t["class_animal"] = conf if ev.entity_class is EntityClass.ANIMAL else 0.0
    if ev.hits is not None:
        t["persistence"] = min(ev.hits / 15.0, 1.0)

    if ev.thermal_confirmed is not None:
        t["thermal_present"] = 1.0 if ev.thermal_confirmed else 0.0
        t["thermal_absent"] = 0.0 if ev.thermal_confirmed else 1.0

    if ev.anomaly_score is not None:
        t["anomaly"] = 2.0 * min(max(ev.anomaly_score, 0.0), 1.0) - 1.0

    imminence = 0.0
    if ev.time_to_breach_s is not None and ev.zone_kind is not ZoneKind.CRITICAL:
        imminence = math.exp(-ev.time_to_breach_s / IMMINENCE_TAU_S)
    t["imminence"] = imminence

    t["authorized_tag"] = 1.0 if ev.authorized_tag and ev.spoof_suspicion < 0.5 else 0.0
    t["spoof"] = min(max(ev.spoof_suspicion, 0.0), 1.0)

    # Independent channels that point toward a threat. Zone membership is not
    # counted: it is present in every in-zone event and corroborates nothing.
    votes = sum(
        (
            (t["class_person"] or 0.0) >= 0.5 or (t["class_vehicle"] or 0.0) >= 0.5,
            t["thermal_present"] == 1.0,
            (ev.anomaly_score or 0.0) >= 0.6,
            imminence >= 0.3,
        )
    )
    t["corroboration"] = 1.0 if votes >= 3 else 0.0
    return t


def fuse(ev: Evidence, w: FusionWeights) -> FusionResult:
    logit = w.bias
    contributions = []
    for name, value in terms(ev).items():
        lo = 0.0 if value is None else w.weights[name] * value
        logit += lo
        contributions.append(ChannelContribution(channel=name, value=value, log_odds=lo))
    probability = 1.0 / (1.0 + math.exp(-logit))
    return FusionResult(probability=probability, logit=logit, contributions=tuple(contributions))
