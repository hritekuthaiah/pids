"""Tracking quality metrics (CLEAR MOT, Bernardin & Stiefelhagen 2008) — AIL-02.

Per frame, ground-truth objects are matched to predicted tracks by IoU (Hungarian,
IoU ≥ 0.5). An **ID switch** is a ground-truth object matched to a different track
than the last time it was matched — the error that breaks behavioural analysis,
because dwell, heading change and loiter history all restart with the new ID.

    MOTA = 1 - (misses + false positives + ID switches) / ground-truth objects
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from pids_edge.detector import iou_matrix


@dataclass
class MotCounter:
    match_iou: float = 0.5
    gt: int = 0
    matches: int = 0
    misses: int = 0
    false_positives: int = 0
    id_switches: int = 0
    #: every track id each ground-truth object was matched to (fragmentation)
    ids_by_object: dict[int, set[int]] = field(default_factory=dict)
    _last: dict[int, int] = field(default_factory=dict, repr=False)

    def frame(
        self,
        gt_ids: list[int],
        gt_boxes: NDArray[np.float32],
        track_ids: list[int],
        track_boxes: NDArray[np.float32],
    ) -> None:
        self.gt += len(gt_ids)
        iou = iou_matrix(gt_boxes, track_boxes)
        pairs: list[tuple[int, int]] = []
        if iou.size:
            r, c = linear_sum_assignment(-iou)
            pairs = [
                (int(i), int(j)) for i, j in zip(r, c, strict=True) if iou[i, j] >= self.match_iou
            ]
        self.matches += len(pairs)
        self.misses += len(gt_ids) - len(pairs)
        self.false_positives += len(track_ids) - len(pairs)
        for i, j in pairs:
            g, t = gt_ids[i], track_ids[j]
            if g in self._last and self._last[g] != t:
                self.id_switches += 1
            self._last[g] = t
            self.ids_by_object.setdefault(g, set()).add(t)

    @property
    def mota(self) -> float:
        if self.gt == 0:
            return 1.0
        return 1.0 - (self.misses + self.false_positives + self.id_switches) / self.gt
