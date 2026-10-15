"""Anomaly-scorer interface (AIL-04).

The decision core depends only on this protocol. The trained Isolation Forest
lives in ``pids_ml`` (it needs scikit-learn, which the core deliberately does not)
and is injected at start-up; until a model is available the engine runs with no
scorer and fusion treats the anomaly channel as *unavailable* — never as
"normal" — so a missing model can't silently suppress alarms.
"""

from __future__ import annotations

from typing import Protocol

from pids_core.features import TrackFeatures


class AnomalyScorer(Protocol):
    """Maps behavioural features to an anomaly score in [0, 1] (1 = most anomalous)."""

    def score(self, features: TrackFeatures) -> float:
        """Anomaly score in [0, 1] for one feature vector."""
