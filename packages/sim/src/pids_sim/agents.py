"""Ground-truth agents: who is in the scene, where they really are, and whether
they are a threat.

Each agent owns a densely sampled true trajectory. Sensors (``sensors.py``) observe
those trajectories with realistic error; the decision engine only ever sees the
observations. Labels (``is_threat``, breach times) come from the true trajectory, so
the evaluation scores the engine against what actually happened.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from pids_core.contracts import EntityClass, ZoneKind
from pids_core.geo import Enu
from pids_core.geofence import ZoneIndex

FloatArray = NDArray[np.float64]
SAMPLE_DT = 0.1


class Role(StrEnum):
    # threats
    INTRUDER_FOOT = "intruder-foot"
    INTRUDER_VEHICLE = "intruder-vehicle"
    PROBER = "fence-prober"
    LOITERER = "loiterer"
    SPOOFER = "spoofed-tag-intruder"
    CLONED_TAG = "cloned-tag-intruder"
    ASSET_THEFT = "asset-theft"
    # normal activity
    PATROL = "patrol"
    STAFF = "staff"
    QRF = "qrf-vehicle"
    ANIMAL = "animal"
    ROAD_VEHICLE = "road-vehicle"
    ROAD_PEDESTRIAN = "road-pedestrian"
    ASSET = "asset"


THREAT_ROLES = frozenset(
    {
        Role.INTRUDER_FOOT,
        Role.INTRUDER_VEHICLE,
        Role.PROBER,
        Role.LOITERER,
        Role.SPOOFER,
        Role.CLONED_TAG,
        Role.ASSET_THEFT,
    }
)


@dataclass(frozen=True, slots=True)
class Trajectory:
    """True positions sampled every ``SAMPLE_DT`` seconds from ``t[0]`` to ``t[-1]``."""

    t: FloatArray
    e: FloatArray
    n: FloatArray

    @property
    def start(self) -> float:
        return float(self.t[0])

    @property
    def end(self) -> float:
        return float(self.t[-1])

    def at(self, time: float) -> Enu | None:
        if time < self.t[0] or time > self.t[-1]:
            return None
        return Enu(float(np.interp(time, self.t, self.e)), float(np.interp(time, self.t, self.n)))

    def first_time_in(self, zones: ZoneIndex, kind: ZoneKind) -> float | None:
        for ti, ei, ni in zip(self.t, self.e, self.n, strict=True):
            if zones.locate(Enu(float(ei), float(ni))).kind is kind:
                return float(ti)
        return None

    def first_time_outside(self, zones: ZoneIndex, zone_id: str) -> float | None:
        for ti, ei, ni in zip(self.t, self.e, self.n, strict=True):
            if not zones.contains(zone_id, Enu(float(ei), float(ni))):
                return float(ti)
        return None


@dataclass(slots=True)
class Agent:
    id: str
    role: Role
    entity_class: EntityClass
    trajectory: Trajectory
    gps_tag: str | None = None
    gps_period_s: float = 1.0
    rfid_tag: str | None = None
    reported_trajectory: Trajectory | None = None  # what a spoofed GPS tag claims
    warm: bool = True
    visible: bool = True  # False for things cameras cannot see (an asset in a crate)
    meta: dict[str, float] = field(default_factory=dict)

    @property
    def is_threat(self) -> bool:
        return self.role in THREAT_ROLES


def path(
    waypoints: list[tuple[float, float]],
    speeds: float | list[float],
    rng: np.random.Generator,
    t0: float = 0.0,
    pauses: dict[int, float] | None = None,
    wobble_m: float = 0.0,
) -> Trajectory:
    """Piecewise-linear path through ``waypoints`` at per-leg ``speeds`` (m/s), with
    optional dwell at waypoint indices and smooth lateral wobble (gait, steering)."""
    if len(waypoints) < 2:
        raise ValueError("a path needs at least two waypoints")
    legs = len(waypoints) - 1
    leg_speeds = [speeds] * legs if isinstance(speeds, float | int) else list(speeds)
    pauses = pauses or {}
    knots_t, knots_e, knots_n = [t0], [waypoints[0][0]], [waypoints[0][1]]
    t = t0
    for i in range(legs):
        if pauses.get(i, 0.0) > 0:
            t += pauses[i]
            knots_t.append(t)
            knots_e.append(waypoints[i][0])
            knots_n.append(waypoints[i][1])
        (e0, n0), (e1, n1) = waypoints[i], waypoints[i + 1]
        t += max(math.hypot(e1 - e0, n1 - n0), 1e-6) / max(float(leg_speeds[i]), 1e-3)
        knots_t.append(t)
        knots_e.append(e1)
        knots_n.append(n1)
    if pauses.get(legs, 0.0) > 0:
        t += pauses[legs]
        knots_t.append(t)
        knots_e.append(waypoints[-1][0])
        knots_n.append(waypoints[-1][1])

    ts = np.arange(t0, t + SAMPLE_DT / 2, SAMPLE_DT)
    e = np.interp(ts, knots_t, knots_e)
    n = np.interp(ts, knots_t, knots_n)
    if wobble_m > 0:
        ph1, ph2 = rng.uniform(0, 2 * math.pi, 2)
        w = wobble_m * (0.7 * np.sin(ts / 3.1 + ph1) + 0.3 * np.sin(ts / 1.3 + ph2))
        de, dn = np.gradient(e), np.gradient(n)
        norm = np.hypot(de, dn)
        norm[norm == 0] = 1.0
        e = e + w * (-dn / norm)
        n = n + w * (de / norm)
    return Trajectory(t=ts, e=e, n=n)


def random_walk(
    start: tuple[float, float],
    duration_s: float,
    speed: float,
    rng: np.random.Generator,
    t0: float = 0.0,
    turn_sigma: float = 0.6,
    pause_prob: float = 0.3,
) -> Trajectory:
    """Correlated random walk with grazing pauses (animals, idle wandering)."""
    pts = [start]
    heading = rng.uniform(0, 2 * math.pi)
    pauses: dict[int, float] = {}
    t, i = 0.0, 0
    while t < duration_s:
        heading += rng.normal(0, turn_sigma)
        leg = rng.uniform(5, 20)
        e, n = pts[-1]
        pts.append((e + leg * math.sin(heading), n + leg * math.cos(heading)))
        t += leg / speed
        if rng.random() < pause_prob:
            pauses[i + 1] = float(rng.uniform(3, 20))
            t += pauses[i + 1]
        i += 1
    return path(pts, speed, rng, t0=t0, pauses=pauses)
