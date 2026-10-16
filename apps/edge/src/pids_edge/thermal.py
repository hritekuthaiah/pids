"""Thermal heat confirmation for camera tracks (AIL-09).

A low-resolution thermal array (MLX90640: 32x24 pixels, ~55 degree field of view)
co-located with the camera answers one question per track: *is there something
warm at that bearing?* People and animals are; shadows, foliage and glare are not.
It confirms heat — it never vetoes. No thermal coverage means ``None``, which the
fusion treats as neutral, never as evidence of absence (ADR-0009).

Only bearings are needed, so a column of the array maps to a bearing by its
horizontal angle; a warm blob is a column whose hottest pixels stand clearly above
the frame's background (median) temperature.
"""

from __future__ import annotations

import logging
import math
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

log = logging.getLogger("pids_edge.thermal")

F32 = NDArray[np.float32]


class ThermalArray(Protocol):
    fov_deg: float

    def frame(self) -> F32 | None:
        """Latest temperature frame in deg C, shape (rows, cols); None if unavailable."""


def warm_at(
    frame: F32,
    relative_bearing_deg: float,
    fov_deg: float,
    *,
    delta_c: float = 4.0,
    window_deg: float = 4.0,
) -> bool | None:
    """Heat at a bearing relative to the array's axis (+ = right), or None if outside view.

    "Warm" means at least two pixels in the bearing's columns exceed the frame median
    by ``delta_c`` — two, so a single hot pixel (sensor noise) is not a person.
    """
    half = fov_deg / 2
    if abs(relative_bearing_deg) > half:
        return None
    cols = frame.shape[1]
    # pinhole geometry: column ~ tan(angle), not linear in angle
    focal = (cols / 2) / math.tan(math.radians(half))

    def col(angle: float) -> int:
        return int(
            np.clip(round(cols / 2 + focal * math.tan(math.radians(angle)) - 0.5), 0, cols - 1)
        )

    lo = col(max(-half, relative_bearing_deg - window_deg / 2))
    hi = col(min(half, relative_bearing_deg + window_deg / 2))
    background = float(np.median(frame))
    strip = frame[:, lo : hi + 1]
    return int((strip > background + delta_c).sum()) >= 2


def relative_bearing(node_heading_deg: float, bearing_deg: float) -> float:
    """Signed angle from the array's axis to a compass bearing, in (-180, 180]."""
    return (bearing_deg - node_heading_deg + 180.0) % 360.0 - 180.0


class Mlx90640:
    """Melexis MLX90640 over I2C (Raspberry Pi). Imported lazily: Pi-only libraries."""

    fov_deg = 55.0

    def __init__(self, refresh_hz: int = 4) -> None:
        import adafruit_mlx90640  # type: ignore[import-not-found]  # Pi-only dependency
        import board  # type: ignore[import-not-found]
        import busio  # type: ignore[import-not-found]

        i2c = busio.I2C(board.SCL, board.SDA, frequency=800_000)
        self._dev = adafruit_mlx90640.MLX90640(i2c)
        rates = {2: "REFRESH_2_HZ", 4: "REFRESH_4_HZ", 8: "REFRESH_8_HZ"}
        self._dev.refresh_rate = getattr(adafruit_mlx90640.RefreshRate, rates[refresh_hz])
        self._buf = [0.0] * 768

    def frame(self) -> F32 | None:
        try:
            self._dev.getFrame(self._buf)
        except (ValueError, RuntimeError, OSError) as exc:  # I2C glitches happen
            log.debug("thermal read failed: %s", exc)
            return None
        return np.asarray(self._buf, dtype=np.float32).reshape(24, 32)


class SyntheticThermal:
    """A thermal array that sees warm bodies at given bearings — tests and bench only.

    Never selected in a live deployment: a fabricated heat signature would be a lie
    to the fusion. The live demo runs without thermal (``thermal: none``).
    """

    def __init__(self, fov_deg: float = 55.0, ambient_c: float = 24.0) -> None:
        self.fov_deg = fov_deg
        self.ambient_c = ambient_c
        self.bodies: list[float] = []  # relative bearings, degrees

    def frame(self) -> F32 | None:
        rng = np.random.default_rng(0)
        img = (self.ambient_c + rng.normal(0, 0.4, (24, 32))).astype(np.float32)
        focal = 16 / math.tan(math.radians(self.fov_deg / 2))
        for b in self.bodies:
            c = round(16 + focal * math.tan(math.radians(b)) - 0.5)
            img[8:20, max(0, c - 1) : c + 2] = 33.0
        return img
