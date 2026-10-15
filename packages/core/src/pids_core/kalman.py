"""Constant-velocity Kalman filter in the site ENU frame (AIL-03, Tier 1).

State ``x = [east, north, v_east, v_north]``. Process noise is the continuous
white-noise-acceleration model, so uncertainty grows realistically with the gap
between measurements (GPS at 1 Hz, vision at 5 Hz, or a dropped frame).

The filter smooths noisy positions, supplies the velocity the behavioural
features and time-to-boundary forecast need, and its velocity covariance tells
the forecaster when an estimate is too uncertain to warn on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

_H = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])


@dataclass(slots=True)
class KalmanCV:
    """Kalman filter with a constant-velocity motion model.

    ``accel_psd``: spectral density of the unmodelled acceleration (m²/s³).
    People manoeuvre more than vehicles relative to their speed, so callers pick
    it per entity class.
    """

    x: Array
    p: Array
    t: float
    accel_psd: float = 0.2

    @classmethod
    def initialise(
        cls,
        t: float,
        east: float,
        north: float,
        sigma_m: float,
        velocity: tuple[float, float] | None = None,
        accel_psd: float = 0.2,
    ) -> KalmanCV:
        ve, vn = velocity if velocity is not None else (0.0, 0.0)
        # Unknown initial velocity: wide prior (±5 m/s) so the first updates dominate.
        v_var = 1.0 if velocity is not None else 25.0
        x = np.array([east, north, ve, vn], dtype=np.float64)
        p = np.diag([sigma_m**2, sigma_m**2, v_var, v_var]).astype(np.float64)
        return cls(x=x, p=p, t=t, accel_psd=accel_psd)

    def predict(self, t: float) -> None:
        dt = t - self.t
        if dt <= 0.0:
            return
        f = np.array(
            [[1.0, 0.0, dt, 0.0], [0.0, 1.0, 0.0, dt], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        )
        q1 = np.array([[dt**3 / 3.0, dt**2 / 2.0], [dt**2 / 2.0, dt]]) * self.accel_psd
        q = np.zeros((4, 4))
        q[np.ix_([0, 2], [0, 2])] = q1
        q[np.ix_([1, 3], [1, 3])] = q1
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + q
        self.t = t

    def update(self, t: float, east: float, north: float, sigma_m: float) -> float:
        """Fuse a position measurement taken at time ``t``.

        Returns the squared Mahalanobis distance of the innovation, which callers
        use as a gating / plausibility statistic (chi-square with 2 dof).
        """
        self.predict(t)
        z = np.array([east, north])
        r = np.eye(2) * max(sigma_m, 0.05) ** 2
        y = z - _H @ self.x
        s = _H @ self.p @ _H.T + r
        s_inv = np.linalg.inv(s)
        k = self.p @ _H.T @ s_inv
        self.x = self.x + k @ y
        # Joseph form keeps P symmetric positive-definite under rounding.
        i_kh = np.eye(4) - k @ _H
        self.p = i_kh @ self.p @ i_kh.T + k @ r @ k.T
        return float(y @ s_inv @ y)

    @property
    def position(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self) -> tuple[float, float]:
        return float(self.x[2]), float(self.x[3])

    @property
    def speed(self) -> float:
        return float(np.hypot(self.x[2], self.x[3]))

    @property
    def velocity_sigma(self) -> float:
        """1-sigma uncertainty of the speed estimate (m/s), isotropic approximation."""
        return float(np.sqrt(max((self.p[2, 2] + self.p[3, 3]) / 2.0, 0.0)))

    def forecast(self, dt: float) -> tuple[float, float]:
        """Mean position ``dt`` seconds ahead without mutating the filter."""
        return float(self.x[0] + self.x[2] * dt), float(self.x[1] + self.x[3] * dt)
