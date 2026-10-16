"""Image -> ground plane: where on the site a tracked object is standing.

A camera looking at flat ground sees it through a planar homography ``H``: the
pixel ``(u, v)`` of a point on the floor maps to site metres ``(east, north)`` by
``[e, n, 1]ᵀ ~ H [u, v, 1]ᵀ``. Four or more floor points with known site
coordinates fix ``H`` (calibration). We project each track's *foot point* — the
bottom-centre of its box, where the person meets the floor.

Localisation uncertainty is propagated, not guessed: the foot point's pixel noise
is pushed through the Jacobian of ``H`` at that pixel, so a person far from the
camera (where one pixel spans more floor) honestly reports a larger sigma — which
is exactly what the decision core's Kalman filter needs to weight the measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from pids_core.geo import Enu

F64 = NDArray[np.float64]

#: Below this many pixels from the frame's bottom edge, a box's feet are likely cut off.
_EDGE_PX = 3.0


class CalibrationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    pixel: tuple[float, float]
    world: tuple[float, float] = Field(description="site metres (east, north)")


class Calibration(BaseModel):
    """A camera's floor homography, as written by ``pids-edge calibrate``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    image_size: tuple[int, int] = Field(description="(width, height) the pixels refer to")
    homography: Annotated[list[list[float]], Field(min_length=3, max_length=3)]
    rms_error_m: Annotated[float, Field(ge=0)]
    method: str
    created_at: AwareDatetime
    points: list[CalibrationPoint] = Field(default_factory=list)

    @property
    def matrix(self) -> F64:
        return np.asarray(self.homography, dtype=np.float64)

    @classmethod
    def load(cls, path: Path) -> Calibration:
        with path.open(encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Floor homography for {self.node_id} (image pixels -> site metres).\n"
            "# Written by `pids-edge calibrate`; re-run it if the camera moves.\n"
        )
        body = yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)
        path.write_text(header + body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def apply(h: F64, points: F64) -> F64:
    """Apply a homography to ``(N, 2)`` points (no horizon check)."""
    pts = np.c_[points, np.ones(len(points))] @ h.T
    return np.asarray(pts[:, :2] / pts[:, 2:3], dtype=np.float64)


def fit(pixels: F64, world: F64) -> tuple[F64, float]:
    """Least-squares homography pixels -> world and its RMS error in metres.

    With six or more points RANSAC rejects a mis-clicked point; with four or five
    there is no redundancy to vote with, so every point is trusted.
    """
    if len(pixels) < 4 or len(pixels) != len(world):
        raise ValueError("need at least 4 matching pixel/world points")
    method = cv2.RANSAC if len(pixels) >= 6 else 0
    h, _ = cv2.findHomography(
        pixels.astype(np.float64), world.astype(np.float64), method, ransacReprojThreshold=0.25
    )
    if h is None:
        raise ValueError("points are degenerate (collinear?) — spread them across the floor")
    hm: F64 = np.asarray(h, dtype=np.float64)
    hm = hm / hm[2, 2]
    residual = np.linalg.norm(apply(hm, pixels) - world, axis=1)
    return hm, float(np.sqrt(np.mean(residual**2)))


def projection(
    *,
    image_size: tuple[int, int],
    hfov_deg: float,
    position: tuple[float, float],
    height_m: float,
    heading_deg: float,
    pitch_deg: float,
) -> F64:
    """3x4 pinhole camera matrix (site metres east/north/up -> pixels) at a known pose.

    ``pitch_deg`` is the downward tilt from level; ``heading_deg`` is the compass
    direction the camera faces. No lens distortion (fine for a ~70 degree webcam).
    """
    w, h = image_size
    f = (w / 2) / math.tan(math.radians(hfov_deg) / 2)
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    psi, theta = math.radians(heading_deg), math.radians(pitch_deg)
    fwd = np.array(
        [math.sin(psi) * math.cos(theta), math.cos(psi) * math.cos(theta), -math.sin(theta)]
    )
    right = np.array([math.cos(psi), -math.sin(psi), 0.0])
    down = np.cross(fwd, right)
    r = np.vstack([right, down, fwd])  # world -> camera (x right, y down, z forward)
    c = np.array([position[0], position[1], height_m])
    return np.asarray(k @ np.c_[r, -r @ c], dtype=np.float64)


def from_pose(
    *,
    image_size: tuple[int, int],
    hfov_deg: float,
    position: tuple[float, float],
    height_m: float,
    heading_deg: float,
    pitch_deg: float,
) -> F64:
    """Floor homography pixels -> world for an ideal camera at a known pose.

    Used for a quick rough calibration from a tape-measured mounting, and as the
    ground-truth camera in tests.
    """
    p = projection(
        image_size=image_size,
        hfov_deg=hfov_deg,
        position=position,
        height_m=height_m,
        heading_deg=heading_deg,
        pitch_deg=pitch_deg,
    )
    inv = np.linalg.inv(p[:, [0, 1, 3]])  # the floor is z = 0: drop the z column
    return np.asarray(inv / inv[2, 2], dtype=np.float64)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FloorFix:
    position: Enu
    sigma_m: float
    feet_visible: bool


class GroundPlane:
    """Projects boxes to site coordinates for one calibrated camera."""

    def __init__(self, calibration: Calibration, frame_size: tuple[int, int] | None = None) -> None:
        self.calibration = calibration
        h = calibration.matrix
        if frame_size is not None and tuple(frame_size) != tuple(calibration.image_size):
            # Same camera at another resolution: rescale pixels into calibration pixels.
            sx = calibration.image_size[0] / frame_size[0]
            sy = calibration.image_size[1] / frame_size[1]
            h = h @ np.diag([sx, sy, 1.0])
        self._h = h
        self._inv = np.linalg.inv(h)
        self.frame_size = frame_size or calibration.image_size

    def to_world(self, u: float, v: float) -> Enu | None:
        """Pixel -> site metres, or None if the pixel is at/above the horizon."""
        p = self._h @ np.array([u, v, 1.0])
        # Points on the floor in front of the camera all share the sign of w at the
        # image centre-bottom; the opposite sign is the sky, mirrored through infinity.
        if p[2] * self._floor_sign <= 1e-12:
            return None
        return Enu(float(p[0] / p[2]), float(p[1] / p[2]))

    def to_image(self, east: float, north: float) -> tuple[float, float] | None:
        """Site metres -> pixel, or None if the point is behind the camera."""
        p = self._inv @ np.array([east, north, 1.0])
        if p[2] * self._floor_sign <= 1e-12:
            return None
        return float(p[0] / p[2]), float(p[1] / p[2])

    @property
    def _floor_sign(self) -> float:
        w, h = self.frame_size
        return float(np.sign((self._h @ np.array([w / 2, h - 1.0, 1.0]))[2]) or 1.0)

    def jacobian(self, u: float, v: float) -> F64:
        """d(east, north) / d(u, v) at a pixel."""
        hm = self._h
        p = hm @ np.array([u, v, 1.0])
        x, y, w = p[0] / p[2], p[1] / p[2], p[2]
        return np.array(
            [
                [(hm[0, 0] - x * hm[2, 0]) / w, (hm[0, 1] - x * hm[2, 1]) / w],
                [(hm[1, 0] - y * hm[2, 0]) / w, (hm[1, 1] - y * hm[2, 1]) / w],
            ]
        )

    def locate(self, box: NDArray[np.float32]) -> FloorFix | None:
        """Where a box's object stands, with its 1-sigma localisation error."""
        x1, y1, x2, y2 = (float(v) for v in box)
        u, v = (x1 + x2) / 2, y2
        bw, bh = x2 - x1, y2 - y1
        feet_visible = v < self.frame_size[1] - _EDGE_PX
        here = self.to_world(u, v)
        if here is None:
            return None
        # Pixel noise of the foot point: the box edge jitters a few percent of its
        # size, the contact point spreads across the stance; if the feet are cut off
        # by the frame edge the true contact is somewhere below — much less certain.
        su = max(2.0, 0.10 * bw)
        sv = max(2.0, 0.04 * bh) if feet_visible else max(4.0, 0.25 * bh)
        j = self.jacobian(u, v)
        cov = j @ np.diag([su**2, sv**2]) @ j.T
        sigma = math.sqrt(float(np.linalg.eigvalsh(cov).max()) + self.calibration.rms_error_m**2)
        return FloorFix(here, sigma, feet_visible)


def calibration_from(
    *,
    node_id: str,
    image_size: tuple[int, int],
    homography: F64,
    rms_error_m: float,
    method: str,
    created_at: datetime,
    points: list[CalibrationPoint] | None = None,
) -> Calibration:
    return Calibration(
        node_id=node_id,
        image_size=image_size,
        homography=[[float(x) for x in row] for row in homography],
        rms_error_m=rms_error_m,
        method=method,
        created_at=created_at,
        points=points or [],
    )
