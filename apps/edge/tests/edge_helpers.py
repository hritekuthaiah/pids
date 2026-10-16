"""Synthetic cameras and scenes for edge tests.

A known pinhole camera looks at the demo room; synthetic people walk on the floor;
their boxes are produced by projecting feet and head through the camera. Because
the ground truth is exact, the perception chain can be checked to centimetres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from pids_edge.camera import Frame
from pids_edge.detector import Detections
from pids_edge.ground import Calibration, calibration_from, from_pose, projection

REPO = Path(__file__).resolve().parents[3]
DEMO_SITE = REPO / "config/sites/demo-room.yaml"
SIZE = (1280, 720)
HFOV, CAM_AT, CAM_HEIGHT, CAM_HEADING, CAM_PITCH = 70.0, (0.3, 5.7), 2.5, 125.0, 28.0
CAMERA = projection(
    image_size=SIZE,
    hfov_deg=HFOV,
    position=CAM_AT,
    height_m=CAM_HEIGHT,
    heading_deg=CAM_HEADING,
    pitch_deg=CAM_PITCH,
)
T0 = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


def true_calibration(rms: float = 0.02) -> Calibration:
    return calibration_from(
        node_id="edge-01",
        image_size=SIZE,
        homography=from_pose(
            image_size=SIZE,
            hfov_deg=HFOV,
            position=CAM_AT,
            height_m=CAM_HEIGHT,
            heading_deg=CAM_HEADING,
            pitch_deg=CAM_PITCH,
        ),
        rms_error_m=rms,
        method="pose",
        created_at=T0,
    )


def project(east: float, north: float, up: float = 0.0) -> tuple[float, float]:
    p = CAMERA @ np.array([east, north, up, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def person_box(
    east: float, north: float, height: float = 1.7, width: float = 0.5
) -> NDArray[np.float32]:
    """Image box of an upright person standing at a floor point."""
    fu, fv = project(east, north)
    _, hv = project(east, north, height)
    h = fv - hv
    w = h * width / height
    return np.array([fu - w / 2, hv, fu + w / 2, fv], np.float32)


def frame(index: int, dt: float = 0.1) -> Frame:
    blank = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    return Frame(blank, index, T0 + timedelta(seconds=index * dt), index * dt)


def dets(
    boxes: list[NDArray[np.float32]], scores: list[float], classes: list[int] | None = None
) -> Detections:
    if not boxes:
        return Detections.empty()
    return Detections(
        np.stack(boxes).astype(np.float32),
        np.array(scores, np.float32),
        np.array(classes or [0] * len(boxes), np.int64),
    )


# ---------------------------------------------------------------------------
# Image-space walker scenes for tracker tests
# ---------------------------------------------------------------------------


@dataclass
class Walker:
    gid: int
    x: float
    y: float
    vx: float
    vy: float
    w: float
    h: float
    occluded: list[tuple[int, int, str]] = field(default_factory=list)  # (from, to, "low"|"gone")

    def box(self, k: int) -> NDArray[np.float32]:
        cx, cy = self.x + self.vx * k, self.y + self.vy * k
        return np.array(
            [cx - self.w / 2, cy - self.h / 2, cx + self.w / 2, cy + self.h / 2], np.float32
        )

    def visibility(self, k: int) -> str:
        for a, b, kind in self.occluded:
            if a <= k < b:
                return kind
        return "clear"


def scene_detections(
    walkers: list[Walker], k: int, rng: np.random.Generator, *, clutter: float = 0.0
) -> tuple[Detections, list[int], NDArray[np.float32]]:
    """Noisy detections for frame ``k`` plus the ground truth that is visible."""
    boxes, scores, gt_ids, gt_boxes = [], [], [], []
    for wk in walkers:
        true = wk.box(k)
        vis = wk.visibility(k)
        if vis == "gone":
            continue
        gt_ids.append(wk.gid)
        gt_boxes.append(true)
        noise = rng.normal(0, 0.015, 4) * np.array([wk.w, wk.h, wk.w, wk.h])
        boxes.append((true + noise).astype(np.float32))
        scores.append(
            float(rng.uniform(0.15, 0.45)) if vis == "low" else float(rng.uniform(0.6, 0.95))
        )
    if clutter and rng.random() < clutter:
        x, y = rng.uniform(0, 1100), rng.uniform(0, 600)
        boxes.append(np.array([x, y, x + 60, y + 120], np.float32))
        scores.append(float(rng.uniform(0.1, 0.4)))
    gt = np.stack(gt_boxes) if gt_boxes else np.zeros((0, 4), np.float32)
    return dets(boxes, scores), gt_ids, gt.astype(np.float32)


def random_scene(rng: np.random.Generator, n: int) -> list[Walker]:
    walkers = []
    for gid in range(n):
        h = float(rng.uniform(120, 360))
        walkers.append(
            Walker(
                gid=gid,
                x=float(rng.uniform(100, 1180)),
                y=float(rng.uniform(200, 520)),
                vx=float(rng.uniform(-6, 6)),
                vy=float(rng.uniform(-1.5, 1.5)),
                w=h * 0.4,
                h=h,
                occluded=[
                    (s, s + int(rng.integers(3, 12)), str(rng.choice(["low", "gone"])))
                    for s in rng.integers(5, 140, size=int(rng.integers(0, 3)))
                ],
            )
        )
    return walkers
