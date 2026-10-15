"""Collect labelled training data by running the simulator through the engine."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from pids_core.anomaly import AnomalyScorer
from pids_core.engine import DecisionEngine, EngineConfig
from pids_core.features import TrackFeatures
from pids_core.fusion import TERMS, FusionWeights
from pids_core.site import Site
from pids_ml.labels import alert_worthy
from pids_sim.agents import Role
from pids_sim.runner import run
from pids_sim.scenarios import Family, ScenarioSpec

FloatArray = NDArray[np.float64]

# Cooperative entities are separated from threats by identity, not behaviour; the
# behaviour model learns what *non-cooperative* traffic normally does at the site.
COOPERATIVE = frozenset({Role.PATROL, Role.QRF, Role.ASSET})


@dataclass(frozen=True, slots=True)
class FeatureRows:
    x: FloatArray  # (n, n_features)
    normal: NDArray[np.bool_]  # True = non-threat, non-cooperative agent (forest training set)
    label: NDArray[np.int8]  # alert-worthy label; -1 = excluded
    cooperative: NDArray[np.bool_]  # tagged patrol / vehicle / asset


@dataclass(frozen=True, slots=True)
class TermRows:
    x: FloatArray  # (n, len(TERMS)) — fusion evidence terms
    y: NDArray[np.int8]


def specs(seeds: Iterable[int], families: Iterable[Family] | None = None) -> list[ScenarioSpec]:
    fams = list(families or Family)
    return [ScenarioSpec(seed=s, family=fams[i % len(fams)]) for i, s in enumerate(seeds)]


def _features_one(
    site_path: Path, spec: ScenarioSpec
) -> tuple[list[list[float]], list[bool], list[int], list[bool]]:
    site = Site.from_yaml(site_path)
    rows: list[tuple[str, float, TrackFeatures]] = []
    engine = DecisionEngine(site, on_features=lambda e, t, f: rows.append((e, t, f)))
    result = run(site, spec, engine, keep_assessments=True)
    zone_at = {(a.entity_id, a.at.timestamp()): a.zone_kind for a in result.assessments}
    xs, normal, labels, coop = [], [], [], []
    for entity_id, t, f in rows:
        agent = result.agent_of(entity_id)
        truth = result.truth.get(agent) if agent else None
        if truth is None:
            continue  # ghost tracks: too short-lived to matter for behaviour
        lab = alert_worthy(truth, t - result.start.timestamp(), zone_at.get((entity_id, t)))
        xs.append(f.to_array().tolist())
        normal.append(not truth.is_threat and truth.role not in COOPERATIVE)
        labels.append(-1 if lab is None else lab)
        coop.append(truth.role in COOPERATIVE)
    return xs, normal, labels, coop


def collect_features(
    site_path: Path, scenario_specs: list[ScenarioSpec], workers: int
) -> FeatureRows:
    xs: list[list[float]] = []
    normal: list[bool] = []
    labels: list[int] = []
    coop: list[bool] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for x, n, lab, c in pool.map(partial(_features_one, site_path), scenario_specs):
            xs += x
            normal += n
            labels += lab
            coop += c
    return FeatureRows(
        x=np.asarray(xs, dtype=np.float64),
        normal=np.asarray(normal, dtype=bool),
        label=np.asarray(labels, dtype=np.int8),
        cooperative=np.asarray(coop, dtype=bool),
    )


def _terms_one(
    site_path: Path,
    scorer_path: Path | None,
    stride: int,
    spec: ScenarioSpec,
) -> tuple[list[list[float]], list[int]]:
    site = Site.from_yaml(site_path)
    scorer: AnomalyScorer | None = None
    if scorer_path is not None:
        from pids_ml.anomaly import IsolationForestScorer

        scorer = IsolationForestScorer.load(scorer_path)
    engine = DecisionEngine(site, EngineConfig(fusion=FusionWeights()), anomaly_scorer=scorer)
    result = run(site, spec, engine, keep_assessments=True)
    xs, ys = [], []
    for i, a in enumerate(result.assessments):
        if i % stride:
            continue
        agent = result.agent_of(a.entity_id)
        truth = result.truth.get(agent) if agent else None
        lab = alert_worthy(truth, result.seconds(a.at), a.zone_kind)
        if lab is None or not a.contributions:
            continue
        values = {c.channel: c.value for c in a.contributions}
        xs.append([float(values[k] or 0.0) for k in TERMS])
        ys.append(lab)
    return xs, ys


def collect_terms(
    site_path: Path,
    scenario_specs: list[ScenarioSpec],
    scorer_path: Path | None,
    workers: int,
    stride: int = 2,
) -> TermRows:
    xs: list[list[float]] = []
    ys: list[int] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for x, y in pool.map(partial(_terms_one, site_path, scorer_path, stride), scenario_specs):
            xs += x
            ys += y
    return TermRows(x=np.asarray(xs, dtype=np.float64), y=np.asarray(ys, dtype=np.int8))
