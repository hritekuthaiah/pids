"""GPS-spoofing detection (AIL-15).

A cooperative tag lowers an entity's threat, which makes tags an attack surface:
an intruder who can make a tag *report* a patrol route while they walk somewhere
else has bought a whitelist. No single test catches every spoofer, so several
cheap, independent plausibility checks feed one leaky suspicion score:

- **Kinematics** — implied speed/acceleration between fixes beyond what the tag's
  carrier can physically do (teleports, replayed tracks spliced together).
- **Filter consistency** — repeated innovations far outside the Kalman filter's
  predicted uncertainty.
- **Signal too clean** — real receivers' accuracy/HDOP jitter; a simulator
  emitting identical quality fix after fix is a classic tell.
- **Clock** — fixes from the future or arriving out of order (replay).
- **Vision disagreement** — the tag claims to stand in a camera's field of view
  while the camera sees nobody there.

Suspicion rises quickly on evidence and decays slowly (half-life ~1 min), so a
single glitch is forgiven but a pattern is not.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field

from pids_core.contracts import TagKind

MAX_SPEED_MPS = {TagKind.PERSON: 8.0, TagKind.VEHICLE: 45.0, TagKind.ASSET: 45.0}
CHI2_2DOF_999 = 13.82
HALF_LIFE_S = 60.0


@dataclass(slots=True)
class SpoofMonitor:
    kind: TagKind
    suspicion: float = 0.0
    reasons: set[str] = field(default_factory=set)
    _last_t: float | None = None
    _last_pos: tuple[float, float] | None = None
    _last_speed: float | None = None
    _last_update_t: float | None = None
    _quality: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=30))
    _unseen_in_view_s: float = 0.0

    def _decay(self, now: float) -> None:
        if self._last_update_t is not None and now > self._last_update_t:
            self.suspicion *= 0.5 ** ((now - self._last_update_t) / HALF_LIFE_S)
            if self.suspicion < 0.01:
                self.suspicion = 0.0
                self.reasons.clear()
        self._last_update_t = now

    def _raise(self, amount: float, reason: str) -> None:
        self.suspicion = min(1.0, self.suspicion + amount)
        self.reasons.add(reason)

    def observe_fix(
        self,
        t: float,
        east: float,
        north: float,
        accuracy_m: float,
        hdop: float | None,
        received_at: float,
    ) -> None:
        self._decay(received_at)
        if t > received_at + 2.0:
            self._raise(0.5, "fix timestamp in the future")
        if self._last_t is not None and t <= self._last_t:
            self._raise(0.4, "out-of-order / replayed fix")
            return

        if self._last_t is not None and self._last_pos is not None:
            dt = t - self._last_t
            dist = math.hypot(east - self._last_pos[0], north - self._last_pos[1])
            # Allow for both fixes' position error before calling a jump.
            speed = max(0.0, dist - 2.0 * accuracy_m) / dt
            limit = MAX_SPEED_MPS[self.kind]
            if speed > limit:
                self._raise(min(0.6, 0.25 * speed / limit), "physically implausible jump")
            elif self._last_speed is not None and dt > 0:
                accel = abs(speed - self._last_speed) / dt
                if accel > 15.0:
                    self._raise(0.15, "implausible acceleration")
            self._last_speed = speed

        self._quality.append((accuracy_m, hdop if hdop is not None else -1.0))
        if len(self._quality) == self._quality.maxlen:
            acc = [q[0] for q in self._quality]
            hd = [q[1] for q in self._quality]
            if statistics.pstdev(acc) < 1e-6 and statistics.pstdev(hd) < 1e-6:
                self._raise(0.05, "signal quality unnaturally constant")

        self._last_t = t
        self._last_pos = (east, north)

    def observe_innovation(self, mahalanobis_sq: float, now: float) -> None:
        self._decay(now)
        if mahalanobis_sq > CHI2_2DOF_999:
            self._raise(0.1, "inconsistent with tracked motion")

    def observe_vision(self, in_view: bool, corroborated: bool, dt: float, now: float) -> None:
        """Feed whether the tag's claimed position is in camera view and seen there."""
        self._decay(now)
        if in_view and not corroborated:
            self._unseen_in_view_s += dt
            if self._unseen_in_view_s > 8.0:
                self._raise(0.04 * dt, "camera sees nobody at the tag's position")
        else:
            self._unseen_in_view_s = 0.0

    def current(self, now: float) -> float:
        self._decay(now)
        return self.suspicion
