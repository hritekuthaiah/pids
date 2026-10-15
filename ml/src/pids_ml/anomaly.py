"""Isolation-Forest behavioural anomaly scorer (AIL-04).

Two stages, both deliberately simple:

1. **Unsupervised:** an Isolation Forest learns the distribution of *normal* site
   movement (patrols, road traffic, animals, staff) — no intrusion labels needed,
   which matters because real breach examples are almost unobtainable.
2. **Calibration:** the forest's raw anomaly score is mapped to a probability with a
   one-feature logistic regression (Platt scaling) on a small labelled set, so the
   number handed to fusion means the same thing as the other channels.

Inference uses a vectorised NumPy walk of the fitted trees rather than
``IsolationForest.score_samples``: identical maths, without scikit-learn's per-call
validation overhead, which dominates when scoring one track at a time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import IsolationForest

from pids_core.features import TrackFeatures

FloatArray = NDArray[np.float64]
_EULER = 0.5772156649

# Hour-of-day is kept out of the forest: simulated normal traffic runs at all
# hours, so it would only add noise. Re-enable once real site data shows a daily
# rhythm worth learning.
FOREST_FEATURES = [n for n in TrackFeatures.names() if not n.startswith("hour_")]
_COLUMNS = np.array([TrackFeatures.names().index(n) for n in FOREST_FEATURES], dtype=np.intp)


def select(x: FloatArray) -> FloatArray:
    """Columns of a full feature matrix/vector that the forest uses."""
    return x[..., _COLUMNS]


def _avg_path(n: FloatArray) -> FloatArray:
    """Average path length of an unsuccessful BST search (Liu et al., 2008)."""
    out = np.zeros_like(n, dtype=np.float64)
    big = n > 2
    out[big] = 2.0 * (np.log(n[big] - 1.0) + _EULER) - 2.0 * (n[big] - 1.0) / n[big]
    out[n == 2] = 1.0
    return out


@dataclass(frozen=True, slots=True)
class _Tree:
    feature: NDArray[np.intp]
    threshold: FloatArray
    left: NDArray[np.intp]
    right: NDArray[np.intp]
    leaf_depth_adj: FloatArray  # depth correction at leaves: c(n_samples_in_leaf)
    features_used: NDArray[np.intp]


class IsolationForestScorer:
    """Implements ``pids_core.anomaly.AnomalyScorer``."""

    def __init__(
        self, forest: IsolationForest, platt_a: float, platt_b: float, prior_logit: float = 0.0
    ) -> None:
        self.forest = forest
        self.platt_a = platt_a
        self.platt_b = platt_b
        self.prior_logit = prior_logit
        self._trees = [
            _Tree(
                feature=est.tree_.feature,
                threshold=est.tree_.threshold,
                left=est.tree_.children_left,
                right=est.tree_.children_right,
                leaf_depth_adj=_avg_path(est.tree_.n_node_samples.astype(np.float64)),
                features_used=np.asarray(feats, dtype=np.intp),
            )
            for est, feats in zip(forest.estimators_, forest.estimators_features_, strict=True)
        ]
        self._norm = float(_avg_path(np.array([float(forest.max_samples_)]))[0])

    def raw(self, x: FloatArray) -> float:
        """Isolation score in (0, 1]: higher = easier to isolate = more anomalous."""
        depth = 0.0
        for tree in self._trees:
            xs = x[tree.features_used]
            node, d = 0, 0
            while tree.left[node] != -1:
                node = (
                    tree.left[node]
                    if xs[tree.feature[node]] <= tree.threshold[node]
                    else tree.right[node]
                )
                d += 1
            depth += d + tree.leaf_depth_adj[node]
        mean_depth = depth / len(self._trees)
        return float(2.0 ** (-mean_depth / self._norm))

    def score(self, features: TrackFeatures) -> float:
        """Behaviour evidence in likelihood-ratio form: 0.5 = uninformative.

        The Platt-calibrated posterior has the training base rate baked in; fusion
        already has its own prior (the bias), so the base rate is removed here.
        Otherwise unremarkable behaviour would *lower* every entity's threat.
        """
        z = self.platt_a * self.raw(select(features.to_array())) + self.platt_b - self.prior_logit
        return 1.0 / (1.0 + math.exp(-z))

    # ------------------------------------------------------------- persistence

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "forest": self.forest,
                "platt_a": self.platt_a,
                "platt_b": self.platt_b,
                "prior_logit": self.prior_logit,
                "features": FOREST_FEATURES,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path) -> IsolationForestScorer:
        blob: dict[str, Any] = joblib.load(path)
        if blob["features"] != FOREST_FEATURES:
            raise ValueError("anomaly model was trained on a different feature set; retrain it")
        return cls(
            blob["forest"],
            float(blob["platt_a"]),
            float(blob["platt_b"]),
            float(blob.get("prior_logit", 0.0)),
        )
