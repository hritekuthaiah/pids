"""Per-track behavioural features (input to anomaly detection, AIL-04).

What separates a threat from a passer-by is rarely a single position — it is how
an entity moves relative to the perimeter: approaching it head-on, walking slowly
*along* the fence probing for a gap, dwelling in the warning ring, moving
erratically, or doing any of that at 3 a.m. These features capture exactly those
patterns from a short sliding window of (smoothed) positions.

The same function feeds training (simulated "normal" traffic) and inference, so
there is no train/serve skew.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import astuple, dataclass, fields

import numpy as np
from numpy.typing import NDArray

from pids_core.contracts import ZoneKind
from pids_core.geo import Enu
from pids_core.geofence import ZoneIndex

WINDOW_S = 30.0
STOP_SPEED = 0.3
NEAR_FENCE_M = 40.0


@dataclass(frozen=True, slots=True)
class Sample:
    t: float
    east: float
    north: float
    zone_kind: ZoneKind | None


@dataclass(frozen=True, slots=True)
class TrackFeatures:
    """Feature vector, in a fixed order shared by training and inference."""

    speed_mean: float
    speed_max: float
    speed_std: float
    turn_rate: float
    tortuosity: float
    stop_fraction: float
    dwell_warning_s: float
    dist_to_critical_m: float
    approach_rate: float
    boundary_parallel: float
    near_fence_s: float
    hour_sin: float
    hour_cos: float

    @classmethod
    def names(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def to_array(self) -> NDArray[np.float64]:
        return np.asarray(astuple(self), dtype=np.float64)


class TrackHistory:
    """Bounded history of samples for one entity."""

    def __init__(self, max_age_s: float = 120.0) -> None:
        self._samples: deque[Sample] = deque()
        self._max_age = max_age_s
        self.dwell_warning_s = 0.0

    def append(self, sample: Sample) -> None:
        if self._samples:
            last = self._samples[-1]
            if sample.t <= last.t:
                return
            if last.zone_kind is ZoneKind.WARNING:
                self.dwell_warning_s += sample.t - last.t
        self._samples.append(sample)
        while self._samples and sample.t - self._samples[0].t > self._max_age:
            self._samples.popleft()

    def window(self, now: float, seconds: float = WINDOW_S) -> list[Sample]:
        return [s for s in self._samples if now - s.t <= seconds]

    def __len__(self) -> int:
        return len(self._samples)

    @property
    def last(self) -> Sample | None:
        return self._samples[-1] if self._samples else None


def extract(
    history: TrackHistory,
    zones: ZoneIndex,
    now: float,
    local_hour: float,
) -> TrackFeatures | None:
    """Features over the last ``WINDOW_S`` seconds; None until there is enough motion data."""
    window = history.window(now)
    if len(window) < 3 or window[-1].t - window[0].t < 2.0:
        return None

    t = np.array([s.t for s in window])
    e = np.array([s.east for s in window])
    n = np.array([s.north for s in window])
    dt = np.diff(t)
    de, dn = np.diff(e), np.diff(n)
    step = np.hypot(de, dn)
    speeds = step / dt

    headings = np.arctan2(de, dn)
    moving = step > 0.05
    turn = 0.0
    if moving.sum() >= 2:
        h = headings[moving]
        dh = np.angle(np.exp(1j * np.diff(h)))  # wrap to (-pi, pi]
        turn = float(np.abs(dh).sum() / (t[-1] - t[0]))

    path = float(step.sum())
    displacement = float(math.hypot(e[-1] - e[0], n[-1] - n[0]))
    tortuosity = path / max(displacement, 1.0)

    first, last = Enu(e[0], n[0]), Enu(e[-1], n[-1])
    d_first = zones.distance_to_kind(ZoneKind.CRITICAL, first)
    d_last = zones.distance_to_kind(ZoneKind.CRITICAL, last)
    approach = (d_first - d_last) / (t[-1] - t[0]) if math.isfinite(d_last) else 0.0

    # Walking *along* the fence matters only near it (probing for a gap); a car on a
    # road 70 m out also moves parallel to the fence and is perfectly ordinary.
    parallel = 0.0
    critical = zones.of_kind(ZoneKind.CRITICAL)
    if critical and displacement > 0.5 and math.isfinite(d_last):
        nearest = min(critical, key=lambda z: abs(zones.signed_distance(z.id, last)))
        tx, ty = zones.boundary_tangent(nearest.id, last)
        ux, uy = (e[-1] - e[0]) / displacement, (n[-1] - n[0]) / displacement
        parallel = abs(tx * ux + ty * uy) * math.exp(-max(d_last, 0.0) / NEAR_FENCE_M)

    near = 0.0
    if critical:
        dists = np.array(
            [
                zones.distance_to_kind(ZoneKind.CRITICAL, Enu(a, b))
                for a, b in zip(e, n, strict=True)
            ]
        )
        outside_near = (dists > 0) & (dists < NEAR_FENCE_M)
        near = float(np.sum(np.where(outside_near[:-1], dt, 0.0)))

    angle = 2.0 * math.pi * (local_hour % 24.0) / 24.0
    return TrackFeatures(
        speed_mean=float(speeds.mean()),
        speed_max=float(speeds.max()),
        speed_std=float(speeds.std()),
        turn_rate=turn,
        tortuosity=float(min(tortuosity, 20.0)),
        stop_fraction=float((speeds < STOP_SPEED).mean()),
        dwell_warning_s=float(min(history.dwell_warning_s, 3600.0)),
        dist_to_critical_m=float(np.clip(d_last, -500.0, 2000.0)),
        approach_rate=float(np.clip(approach, -30.0, 30.0)),
        boundary_parallel=parallel,
        near_fence_s=near,
        hour_sin=math.sin(angle),
        hour_cos=math.cos(angle),
    )
