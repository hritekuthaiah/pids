from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from pids_core.contracts import ZoneKind
from pids_core.engine import DecisionModel
from pids_core.features import TrackFeatures
from pids_core.fusion import TERMS
from pids_ml.anomaly import FOREST_FEATURES, IsolationForestScorer, select
from pids_ml.fusion_fit import BOUNDS, fit_constrained
from pids_ml.labels import alert_worthy
from pids_sim.agents import Role
from pids_sim.runner import AgentTruth

ROOT = Path(__file__).resolve().parents[2]


def test_numpy_forest_matches_sklearn_exactly() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(500, len(FOREST_FEATURES)))
    forest = IsolationForest(n_estimators=40, max_samples=128, random_state=1).fit(x)
    scorer = IsolationForestScorer(forest, 1.0, 0.0)
    probe = rng.normal(size=(50, len(FOREST_FEATURES))) * 2
    ours = np.array([scorer.raw(p) for p in probe])
    # sklearn's score_samples is the negated isolation score
    np.testing.assert_allclose(ours, -forest.score_samples(probe), rtol=1e-9)


def test_scorer_round_trip_and_neutral_centre(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    forest = IsolationForest(n_estimators=10, random_state=0).fit(
        rng.normal(size=(200, len(FOREST_FEATURES)))
    )
    s = IsolationForestScorer(forest, platt_a=0.0, platt_b=-0.4, prior_logit=-0.4)
    f = TrackFeatures(*([0.0] * len(TrackFeatures.names())))
    assert s.score(f) == pytest.approx(0.5)  # base rate removed -> uninformative
    s.save(tmp_path / "m.joblib")
    loaded = IsolationForestScorer.load(tmp_path / "m.joblib")
    assert loaded.score(f) == pytest.approx(s.score(f))


def test_forest_ignores_hour_of_day() -> None:
    assert not any(n.startswith("hour_") for n in FOREST_FEATURES)
    assert select(np.zeros(len(TrackFeatures.names()))).shape == (len(FOREST_FEATURES),)


def test_constrained_fit_respects_sign_bounds() -> None:
    rng = np.random.default_rng(3)
    x = rng.random((4000, len(TERMS)))
    # a target that "wants" a wrong sign on thermal_absent and class_animal
    logits = 3 * x[:, TERMS.index("zone_critical")] + 2 * x[:, TERMS.index("thermal_absent")] - 2
    y = (rng.random(4000) < 1 / (1 + np.exp(-logits))).astype(np.int8)
    fit = fit_constrained(x, y)
    for k, (lo, hi) in BOUNDS.items():
        assert lo - 1e-9 <= fit.weights[k] <= hi + 1e-9, k
    assert fit.weights["thermal_absent"] <= 0.0
    assert fit.weights["zone_critical"] > 1.0


def test_label_policy() -> None:
    normal = AgentTruth("a", Role.PATROL, False, None, None, None)
    intruder = AgentTruth("t", Role.INTRUDER_FOOT, True, 50.0, 100.0, None)
    assert alert_worthy(None, 10, None) == 0
    assert alert_worthy(normal, 10, ZoneKind.CRITICAL) == 0
    assert alert_worthy(intruder, 10, None) is None  # far out: excluded, not negative
    assert alert_worthy(intruder, 60, None) == 1  # within the lead window
    assert alert_worthy(intruder, 20, ZoneKind.WARNING) == 1


def test_committed_decision_model_is_valid_and_recall_biased() -> None:
    model = DecisionModel.load(ROOT / "config/models/decision-model.json")
    assert model.fusion.source == "fitted"
    assert model.scoring.warning_at <= 0.5
    assert model.fusion.weights["authorized_tag"] < 0
    assert model.fusion.weights["zone_critical"] > 0
