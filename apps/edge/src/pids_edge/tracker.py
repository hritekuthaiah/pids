"""ByteTrack multi-object tracking (Zhang et al., "ByteTrack: Multi-Object Tracking by
Associating Every Detection Box", ECCV 2022) — AIL-02.

The insight that makes it the right tracker here: low-confidence detections are not
thrown away. A person half-hidden behind a pillar scores 0.2 and a naive tracker
drops them — and loses the ID the behavioural model depends on. ByteTrack first
matches confident detections to tracks, then gives the *remaining* tracks a second
chance against the low-score detections, which are mostly real objects partly
occluded rather than clutter (clutter rarely lines up with a predicted track).

Motion model: constant velocity in image space over ``(cx, cy, aspect, height)``.
Association: IoU (fused with detection score in the first stage), Hungarian.
Faithful to the reference implementation; the only change is that the lost-track
buffer is in seconds, because the edge frame rate is inference-bound, not fixed.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from pids_core.contracts import EntityClass
from pids_edge.config import TrackerConfig
from pids_edge.detector import CLASS_ORDER, Detections, iou_matrix

F64 = NDArray[np.float64]

_CLASS_EMA = 0.3

# ---------------------------------------------------------------------------
# Kalman filter in image space
# ---------------------------------------------------------------------------

_STD_POS = 1.0 / 20.0
_STD_VEL = 1.0 / 160.0
_F = np.eye(8)
_F[:4, 4:] = np.eye(4)
_H = np.eye(4, 8)


def _xyah(box: NDArray[np.float32]) -> F64:
    x1, y1, x2, y2 = (float(v) for v in box)
    h = max(y2 - y1, 1e-3)
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / h, h])


def _initiate(z: F64) -> tuple[F64, F64]:
    h = z[3]
    mean = np.concatenate([z, np.zeros(4)])
    std = [
        2 * _STD_POS * h, 2 * _STD_POS * h, 1e-2, 2 * _STD_POS * h,
        10 * _STD_VEL * h, 10 * _STD_VEL * h, 1e-5, 10 * _STD_VEL * h,
    ]  # fmt: skip
    return mean, np.diag(np.square(std))


def _predict(mean: F64, cov: F64) -> tuple[F64, F64]:
    h = mean[3]
    std = [
        _STD_POS * h, _STD_POS * h, 1e-2, _STD_POS * h,
        _STD_VEL * h, _STD_VEL * h, 1e-5, _STD_VEL * h,
    ]  # fmt: skip
    return _F @ mean, _F @ cov @ _F.T + np.diag(np.square(std))


def _update(mean: F64, cov: F64, z: F64) -> tuple[F64, F64]:
    h = mean[3]
    r = np.diag(np.square([_STD_POS * h, _STD_POS * h, 1e-1, _STD_POS * h]))
    s = _H @ cov @ _H.T + r
    gain = np.linalg.solve(s, _H @ cov).T  # cov H^T S^-1, S symmetric
    mean = mean + gain @ (z - _H @ mean)
    cov = cov - gain @ s @ gain.T
    return mean, cov


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


class TrackState(IntEnum):
    TRACKED = 1
    LOST = 2
    REMOVED = 3


@dataclass(eq=False)
class Track:
    track_id: int
    mean: F64
    cov: F64
    score: float
    class_scores: F64
    started_at: float
    last_seen: float
    state: TrackState = TrackState.TRACKED
    activated: bool = False
    hits: int = 1
    #: Set on the frame a track was matched; ``ByteTracker.update`` reports only these.
    updated: bool = True
    _box: NDArray[np.float32] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._sync_box()

    def _sync_box(self) -> None:
        cx, cy, a, h = self.mean[:4]
        w = a * h
        self._box = np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], np.float32)

    @property
    def box(self) -> NDArray[np.float32]:
        """Current (filtered) box, x1 y1 x2 y2 in image pixels."""
        return self._box

    @property
    def entity_class(self) -> EntityClass:
        return CLASS_ORDER[int(np.argmax(self.class_scores))]

    @property
    def class_confidence(self) -> float:
        return float(min(1.0, self.class_scores.max()))

    def predict(self) -> None:
        mean = self.mean.copy()
        if self.state is not TrackState.TRACKED:
            mean[7] = 0.0  # a lost track's height stops changing (reference behaviour)
        self.mean, self.cov = _predict(mean, self.cov)
        self._sync_box()

    def absorb(self, box: NDArray[np.float32], score: float, cls: int, t: float) -> None:
        self.mean, self.cov = _update(self.mean, self.cov, _xyah(box))
        self._sync_box()
        onehot = np.zeros(len(CLASS_ORDER))
        onehot[cls] = score
        self.class_scores = (1 - _CLASS_EMA) * self.class_scores + _CLASS_EMA * onehot
        self.score = score
        self.state = TrackState.TRACKED
        self.activated = True
        self.hits += 1
        self.last_seen = t
        self.updated = True


# ---------------------------------------------------------------------------
# Association
# ---------------------------------------------------------------------------


def _assign(cost: F64, max_cost: float) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Min-cost matching that refuses any pair costing more than ``max_cost``."""
    rows, cols = cost.shape
    if rows == 0 or cols == 0:
        return [], list(range(rows)), list(range(cols))
    gated = np.where(cost > max_cost, max_cost + 1e3, cost)
    r, c = linear_sum_assignment(gated)
    matches = [(int(i), int(j)) for i, j in zip(r, c, strict=True) if cost[i, j] <= max_cost]
    mr = {i for i, _ in matches}
    mc = {j for _, j in matches}
    return matches, [i for i in range(rows) if i not in mr], [j for j in range(cols) if j not in mc]


def _boxes(tracks: list[Track]) -> NDArray[np.float32]:
    if not tracks:
        return np.zeros((0, 4), np.float32)
    return np.stack([t.box for t in tracks])


class ByteTracker:
    """Stable per-camera track IDs from per-frame detections."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._tracked: list[Track] = []
        self._lost: list[Track] = []
        self._ids = itertools.count(1)
        self._frames = 0

    @property
    def tracks(self) -> list[Track]:
        """Confirmed tracks matched in the latest frame."""
        return [t for t in self._tracked if t.activated and t.updated]

    def update(self, dets: Detections, t: float) -> list[Track]:
        """Advance one frame captured at ``t`` (seconds, monotonic)."""
        cfg = self.config
        self._frames += 1
        for tr in itertools.chain(self._tracked, self._lost):
            tr.updated = False

        high = dets.subset(dets.scores >= cfg.high_threshold)
        low = dets.subset((dets.scores >= cfg.low_threshold) & (dets.scores < cfg.high_threshold))

        confirmed = [tr for tr in self._tracked if tr.activated]
        unconfirmed = [tr for tr in self._tracked if not tr.activated]
        pool = confirmed + self._lost
        for tr in pool:
            tr.predict()

        # Stage 1: every live or recently-lost track vs confident detections.
        cost = 1.0 - iou_matrix(_boxes(pool), high.boxes) * high.scores[None, :]
        matches, rest_tracks, rest_high = _assign(cost.astype(np.float64), 1.0 - cfg.match_iou)
        for i, j in matches:
            pool[i].absorb(high.boxes[j], float(high.scores[j]), int(high.classes[j]), t)

        # Stage 2: still-unmatched *live* tracks vs low-score detections (occlusion).
        second = [pool[i] for i in rest_tracks if pool[i].state is TrackState.TRACKED]
        cost = 1.0 - iou_matrix(_boxes(second), low.boxes)
        matches, rest_second, _ = _assign(cost.astype(np.float64), 1.0 - cfg.low_match_iou)
        for i, j in matches:
            second[i].absorb(low.boxes[j], float(low.scores[j]), int(low.classes[j]), t)
        for i in rest_second:
            second[i].state = TrackState.LOST

        # Tentative tracks (seen once) must be confirmed by a confident detection now.
        remaining = high.subset(np.isin(np.arange(len(high)), rest_high))
        cost = 1.0 - iou_matrix(_boxes(unconfirmed), remaining.boxes) * remaining.scores[None, :]
        matches, rest_unconf, rest_new = _assign(
            cost.astype(np.float64), 1.0 - cfg.unconfirmed_match_iou
        )
        for i, j in matches:
            unconfirmed[i].absorb(
                remaining.boxes[j], float(remaining.scores[j]), int(remaining.classes[j]), t
            )
        for i in rest_unconf:
            unconfirmed[i].state = TrackState.REMOVED

        # Births: confident, unexplained detections start tentative tracks.
        born: list[Track] = []
        for j in rest_new:
            score = float(remaining.scores[j])
            if score < cfg.new_track_threshold:
                continue
            mean, cov = _initiate(_xyah(remaining.boxes[j]))
            onehot = np.zeros(len(CLASS_ORDER))
            onehot[int(remaining.classes[j])] = score
            born.append(
                Track(
                    track_id=next(self._ids),
                    mean=mean,
                    cov=cov,
                    score=score,
                    class_scores=onehot,
                    started_at=t,
                    last_seen=t,
                    # The very first frame has no history to confirm against.
                    activated=self._frames == 1,
                )
            )

        everyone = [*pool, *unconfirmed, *born]
        tracked = [tr for tr in everyone if tr.state is TrackState.TRACKED]
        lost = [
            tr
            for tr in everyone
            if tr.state is TrackState.LOST and t - tr.last_seen <= cfg.lost_buffer_s
        ]
        self._tracked, self._lost = _dedupe(tracked, lost)
        return self.tracks


def _dedupe(tracked: list[Track], lost: list[Track]) -> tuple[list[Track], list[Track]]:
    """A lost track re-found as a new one leaves two copies; keep the older (reference)."""
    if not tracked or not lost:
        return tracked, lost
    overlap = iou_matrix(_boxes(tracked), _boxes(lost))
    drop_t: set[int] = set()
    drop_l: set[int] = set()
    for i, j in zip(*np.nonzero(overlap > 0.85), strict=True):
        a, b = tracked[int(i)], lost[int(j)]
        if a.last_seen - a.started_at > b.last_seen - b.started_at:
            drop_l.add(int(j))
        else:
            drop_t.add(int(i))
    return (
        [tr for k, tr in enumerate(tracked) if k not in drop_t],
        [tr for k, tr in enumerate(lost) if k not in drop_l],
    )
