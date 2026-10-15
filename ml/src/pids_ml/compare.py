"""Event-level comparison of decision engines over simulated scenarios.

Per-sample calibration metrics are a proxy; what matters operationally is the
probability of detecting each threat (Pd), nuisance alarms per hour (NAR) and lead
time. This module runs engines over a seed range in parallel and reports those.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from pids_core.baseline import NaiveGeofence
from pids_core.engine import DecisionEngine, DecisionModel, EngineConfig
from pids_core.site import Site
from pids_ml.anomaly import IsolationForestScorer
from pids_sim.outcomes import RunOutcome, score_run
from pids_sim.runner import Engine, run
from pids_sim.scenarios import Family, ScenarioSpec


@dataclass(frozen=True, slots=True)
class EngineSpec:
    """Picklable description of an engine variant."""

    kind: str  # "pids" | "line-crossing" | "gps-only"
    weights: Path | None = None  # a DecisionModel JSON file
    anomaly: Path | None = None
    warning_at: float | None = None

    def build(self, site: Site) -> Engine:
        if self.kind == "line-crossing":
            return NaiveGeofence(site, "line-crossing")
        if self.kind == "gps-only":
            return NaiveGeofence(site, "gps-only")
        model = DecisionModel.load(self.weights) if self.weights else DecisionModel()
        weights, scoring = model.fusion, model.scoring
        scorer = IsolationForestScorer.load(self.anomaly) if self.anomaly else None
        if self.warning_at is not None:
            scoring = scoring.model_copy(
                update={"warning_at": self.warning_at, "critical_at": self.warning_at}
            )
        return DecisionEngine(
            site, EngineConfig(fusion=weights, scoring=scoring), anomaly_scorer=scorer
        )


@dataclass(frozen=True, slots=True)
class Summary:
    name: str
    pd: float
    detected: int
    threats: int
    nar_per_hour: float
    median_lead_s: float | None
    missed: list[tuple[str, int]]
    nuisance_by_role: dict[str, int]

    def line(self) -> str:
        lead = f"{self.median_lead_s:6.1f}s" if self.median_lead_s is not None else "    n/a"
        return (
            f"{self.name:22s} Pd={self.pd:6.1%} ({self.detected}/{self.threats})  "
            f"NAR={self.nar_per_hour:6.1f}/h  median lead={lead}"
        )


def _one(site_path: Path, engine: EngineSpec, spec: ScenarioSpec) -> RunOutcome:
    site = Site.from_yaml(site_path)
    return score_run(run(site, spec, engine.build(site)))


def scenario_specs(seed0: int, per_family: int) -> list[ScenarioSpec]:
    return [
        ScenarioSpec(seed=seed0 + 1000 * f + i, family=fam)
        for f, fam in enumerate(Family)
        for i in range(per_family)
    ]


def evaluate(
    name: str, engine: EngineSpec, site_path: Path, specs: list[ScenarioSpec], workers: int
) -> Summary:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(partial(_one, site_path, engine), specs))
    return summarise(name, outcomes)


def summarise(name: str, outcomes: list[RunOutcome]) -> Summary:
    threats = [(o, t) for o in outcomes for t in o.threats]
    detected = [t for _, t in threats if t.detected]
    hours = sum(o.duration_s for o in outcomes) / 3600.0
    leads = [t.lead_time_s for t in detected if t.lead_time_s is not None]
    by_role: dict[str, int] = {}
    for o in outcomes:
        for k, v in o.nuisance_by_role.items():
            by_role[k] = by_role.get(k, 0) + v
    return Summary(
        name=name,
        pd=len(detected) / len(threats) if threats else float("nan"),
        detected=len(detected),
        threats=len(threats),
        nar_per_hour=sum(o.nuisance_alarms for o in outcomes) / hours,
        median_lead_s=statistics.median(leads) if leads else None,
        missed=[(o.family, o.seed) for o, t in threats if not t.detected],
        nuisance_by_role=dict(sorted(by_role.items(), key=lambda kv: -kv[1])),
    )


EngineFactory = Callable[[Site], Engine]
