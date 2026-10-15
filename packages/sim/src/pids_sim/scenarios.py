"""Scenario generation: seeded mixes of one threat (or none) and background activity.

Every scenario contains the ordinary life of the site — patrols with GPS phones,
public-road traffic through the warning band, grazing animals, staff badging in at
the gate, the quick-reaction vehicle, a stored asset — because nuisance alarms come
from exactly that background. Threat families add one adversary whose approach is
placed inside camera coverage (coverage gaps are a deployment property, reported
separately, not something a fusion algorithm can fix).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import numpy as np
from shapely.geometry import Point

from pids_core.contracts import EntityClass, ZoneKind
from pids_core.site import NodeConfig, Site
from pids_sim.agents import Agent, Role, Trajectory, path, random_walk

DEFAULT_DURATION_S = 300.0


class Family(StrEnum):
    NORMAL = "normal"
    INTRUSION_FOOT = "intrusion-foot"
    INTRUSION_VEHICLE = "intrusion-vehicle"
    PROBE = "probe"
    LOITER = "loiter"
    SPOOFED_TAG = "spoofed-tag"
    CLONED_TAG = "cloned-tag"
    ASSET_THEFT = "asset-theft"


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    seed: int
    family: Family
    duration_s: float = DEFAULT_DURATION_S
    night: bool | None = None


@dataclass(slots=True)
class Scenario:
    spec: ScenarioSpec
    start: datetime
    agents: list[Agent] = field(default_factory=list)


def _polar(origin: tuple[float, float], bearing_deg: float, r: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    return origin[0] + r * math.sin(b), origin[1] + r * math.cos(b)


def _outward_nodes(site: Site) -> list[NodeConfig]:
    """Fence cameras that look outward over an approach (not 360-degree masts)."""
    return [n for n in site.config.nodes if n.fov_deg < 360]


def _critical_point_near(
    site: Site, p: tuple[float, float], inside_m: float
) -> tuple[float, float]:
    """The nearest point on the critical boundary to ``p``, pushed ``inside_m`` inward."""
    zone = site.zones.of_kind(ZoneKind.CRITICAL)[0]
    ring = zone.polygon.exterior
    q = ring.interpolate(ring.project(Point(p)))
    c = zone.polygon.centroid
    dx, dy = c.x - q.x, c.y - q.y
    d = math.hypot(dx, dy) or 1.0
    return q.x + inside_m * dx / d, q.y + inside_m * dy / d


def _approach(site: Site, rng: np.random.Generator) -> tuple[NodeConfig, tuple[float, float]]:
    node = _outward_nodes(site)[int(rng.integers(len(_outward_nodes(site))))]
    bearing = node.heading_deg + rng.uniform(-0.35, 0.35) * node.fov_deg
    start = _polar(node.position, bearing, rng.uniform(0.75, 0.95) * node.range_m)
    return node, start


# ---------------------------------------------------------------- background


def _background(site: Site, rng: np.random.Generator, dur: float) -> list[Agent]:
    agents: list[Agent] = []
    routes = site.config.features.patrol_routes
    for i, name in enumerate(rng.permutation(sorted(routes))[: int(rng.integers(1, 3))]):
        pts = routes[str(name)]
        k = int(rng.integers(len(pts) - 1))
        loop = pts[k:] + pts[1 : k + 1]
        speed = float(rng.uniform(1.1, 1.5))
        agents.append(
            Agent(
                id=f"patrol-{i}",
                role=Role.PATROL,
                entity_class=EntityClass.PERSON,
                trajectory=path(loop * 3, speed, rng, wobble_m=0.4),
                gps_tag=("patrol-alpha", "patrol-bravo")[i],
            )
        )

    road = next(iter(site.config.features.roads.values()), None)
    if road:
        for i in range(int(rng.poisson(2.0))):
            pts = road if rng.random() < 0.5 else road[::-1]
            agents.append(
                Agent(
                    id=f"road-vehicle-{i}",
                    role=Role.ROAD_VEHICLE,
                    entity_class=EntityClass.VEHICLE,
                    trajectory=path(
                        pts, float(rng.uniform(8, 15)), rng, t0=rng.uniform(0, dur), wobble_m=0.3
                    ),
                )
            )
        for i in range(int(rng.poisson(1.0))):
            pts = road if rng.random() < 0.5 else road[::-1]
            agents.append(
                Agent(
                    id=f"road-pedestrian-{i}",
                    role=Role.ROAD_PEDESTRIAN,
                    entity_class=EntityClass.PERSON,
                    trajectory=path(
                        pts,
                        float(rng.uniform(1.0, 1.5)),
                        rng,
                        t0=rng.uniform(-200, dur),
                        wobble_m=0.5,
                    ),
                )
            )

    warning = site.zones.of_kind(ZoneKind.WARNING)[0].polygon
    minx, _, maxx, maxy = warning.bounds
    for i in range(int(rng.integers(0, 4))):
        start = (float(rng.uniform(minx, maxx)), float(rng.uniform(maxy - 60, maxy)))
        agents.append(
            Agent(
                id=f"animal-{i}",
                role=Role.ANIMAL,
                entity_class=EntityClass.ANIMAL,
                trajectory=random_walk(
                    start, dur, float(rng.uniform(0.4, 1.2)), rng, t0=rng.uniform(-30, 30)
                ),
            )
        )

    gate = site.config.features.gates.get("south-gate")
    if gate and rng.random() < 0.5:
        agents.append(
            Agent(
                id="staff-0",
                role=Role.STAFF,
                entity_class=EntityClass.PERSON,
                trajectory=path(
                    [
                        (gate[0] - 60, gate[1] - 70),
                        (gate[0], gate[1] - 6),
                        gate,
                        (gate[0] + 5, gate[1] + 70),
                    ],
                    1.3,
                    rng,
                    t0=rng.uniform(0, dur * 0.6),
                    pauses={2: 4.0},
                    wobble_m=0.3,
                ),
                rfid_tag="badge-0142",
            )
        )
    if gate and road and rng.random() < 0.3:
        agents.append(
            Agent(
                id="qrf-0",
                role=Role.QRF,
                entity_class=EntityClass.VEHICLE,
                trajectory=path(
                    [
                        road[0],
                        (gate[0] - 20, road[0][1] + 10),
                        (gate[0], gate[1] - 10),
                        (gate[0], gate[1] + 60),
                    ],
                    [12.0, 6.0, 4.0],
                    rng,
                    t0=rng.uniform(0, dur * 0.6),
                ),
                gps_tag="qrf-jeep",
            )
        )

    armoury = site.zones["armoury"].polygon.centroid
    agents.append(
        Agent(
            id="asset-0",
            role=Role.ASSET,
            entity_class=EntityClass.UNKNOWN,
            trajectory=Trajectory(
                t=np.array([-10.0, dur + 10]),
                e=np.array([armoury.x, armoury.x]),
                n=np.array([armoury.y, armoury.y]),
            ),
            gps_tag="crate-07",
            gps_period_s=10.0,
            visible=False,
            warm=False,
        )
    )
    return agents


# ------------------------------------------------------------------- threats


def _intruder_foot(site: Site, rng: np.random.Generator, dur: float) -> Agent:
    _, start = _approach(site, rng)
    fence = _critical_point_near(site, start, inside_m=0.0)
    inside = _critical_point_near(site, start, inside_m=float(rng.uniform(25, 60)))
    mid = (
        (start[0] + fence[0]) / 2 + rng.normal(0, 15),
        (start[1] + fence[1]) / 2 + rng.normal(0, 15),
    )
    speed = float(rng.uniform(1.0, 1.8))
    return Agent(
        id="threat",
        role=Role.INTRUDER_FOOT,
        entity_class=EntityClass.PERSON,
        trajectory=path(
            [start, mid, fence, inside],
            [speed, speed * 0.8, speed],
            rng,
            t0=float(rng.uniform(5, dur * 0.3)),
            pauses={1: float(rng.uniform(0, 25)), 2: float(rng.uniform(0, 10))},
            wobble_m=0.6,
        ),
    )


def _intruder_vehicle(site: Site, rng: np.random.Generator, dur: float) -> Agent:
    _, start = _approach(site, rng)
    fence = _critical_point_near(site, start, inside_m=0.0)
    inside = _critical_point_near(site, start, inside_m=float(rng.uniform(30, 70)))
    return Agent(
        id="threat",
        role=Role.INTRUDER_VEHICLE,
        entity_class=EntityClass.VEHICLE,
        trajectory=path(
            [start, fence, inside],
            [float(rng.uniform(5, 12)), float(rng.uniform(3, 6))],
            rng,
            t0=float(rng.uniform(5, dur * 0.4)),
            wobble_m=0.3,
        ),
    )


def _prober(site: Site, rng: np.random.Generator, dur: float) -> Agent:
    node, start = _approach(site, rng)
    near = _critical_point_near(site, node.position, inside_m=-float(rng.uniform(12, 30)))
    zone = site.zones.of_kind(ZoneKind.CRITICAL)[0].polygon
    c = zone.centroid
    # walk along the fence: tangent = perpendicular to the inward direction
    dx, dy = c.x - near[0], c.y - near[1]
    d = math.hypot(dx, dy) or 1.0
    tx, ty = -dy / d, dx / d
    length = float(rng.uniform(50, 110))
    a = (near[0] - tx * length / 2, near[1] - ty * length / 2)
    b = (near[0] + tx * length / 2, near[1] + ty * length / 2)
    speed = float(rng.uniform(0.5, 0.9))
    return Agent(
        id="threat",
        role=Role.PROBER,
        entity_class=EntityClass.PERSON,
        trajectory=path(
            [start, a, b, a, start],
            [1.3, speed, speed, 1.3],
            rng,
            t0=float(rng.uniform(5, dur * 0.2)),
            pauses={1: float(rng.uniform(5, 20)), 2: float(rng.uniform(5, 20))},
            wobble_m=0.4,
        ),
    )


def _loiterer(site: Site, rng: np.random.Generator, dur: float) -> Agent:
    _, start = _approach(site, rng)
    spot = _critical_point_near(site, start, inside_m=-float(rng.uniform(20, 50)))
    linger = random_walk(spot, float(rng.uniform(120, 200)), 0.3, rng, pause_prob=0.6)
    lead = path([start, spot], 1.2, rng)
    t0 = float(rng.uniform(5, dur * 0.2))
    e = np.concatenate([lead.e, linger.e])
    n = np.concatenate([lead.n, linger.n])
    t = t0 + np.arange(len(e), dtype=np.float64) * 0.1
    return Agent(
        id="threat",
        role=Role.LOITERER,
        entity_class=EntityClass.PERSON,
        trajectory=Trajectory(t, e, n),
    )


def _spoofed(site: Site, rng: np.random.Generator, dur: float) -> Agent:
    agent = _intruder_foot(site, rng, dur)
    route = site.config.features.patrol_routes["inner-fence"]
    agent.role = Role.SPOOFER
    agent.gps_tag = "patrol-bravo"
    agent.reported_trajectory = path(route * 3, 1.3, rng, t0=0.0, wobble_m=0.3)
    return agent


def _cloned(site: Site, rng: np.random.Generator, dur: float) -> Agent:
    agent = _intruder_foot(site, rng, dur)
    agent.role = Role.CLONED_TAG
    agent.gps_tag = "patrol-bravo"  # carried by the intruder: reports the true path
    return agent


def _asset_theft(site: Site, rng: np.random.Generator, dur: float, agents: list[Agent]) -> Agent:
    asset = next(a for a in agents if a.role is Role.ASSET)
    agents.remove(asset)
    c = site.zones["armoury"].polygon.centroid
    t0 = float(rng.uniform(20, dur * 0.4))
    exit_pt = _critical_point_near(site, (c.x + rng.normal(0, 50), c.y - 150), inside_m=-20.0)
    carried = path([(c.x, c.y), (c.x, c.y - 40), exit_pt], 1.2, rng, t0=t0, wobble_m=0.3)
    still = Trajectory(t=np.array([-10.0, t0]), e=np.array([c.x, c.x]), n=np.array([c.y, c.y]))
    traj = Trajectory(
        t=np.concatenate([still.t, carried.t[1:]]),
        e=np.concatenate([still.e, carried.e[1:]]),
        n=np.concatenate([still.n, carried.n[1:]]),
    )
    return Agent(
        id="threat",
        role=Role.ASSET_THEFT,
        entity_class=EntityClass.UNKNOWN,
        trajectory=traj,
        gps_tag="crate-07",
        gps_period_s=10.0,
        visible=False,
        warm=False,
    )


def build(site: Site, spec: ScenarioSpec) -> Scenario:
    rng = np.random.default_rng(spec.seed)
    night = spec.night if spec.night is not None else bool(rng.random() < 0.6)
    hour = float(rng.uniform(21, 29) % 24) if night else float(rng.uniform(7, 19))
    start = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(
        days=int(rng.integers(0, 30)), hours=hour - 5.5
    )
    agents = _background(site, rng, spec.duration_s)
    dur = spec.duration_s
    match spec.family:
        case Family.NORMAL:
            pass
        case Family.INTRUSION_FOOT:
            agents.append(_intruder_foot(site, rng, dur))
        case Family.INTRUSION_VEHICLE:
            agents.append(_intruder_vehicle(site, rng, dur))
        case Family.PROBE:
            agents.append(_prober(site, rng, dur))
        case Family.LOITER:
            agents.append(_loiterer(site, rng, dur))
        case Family.SPOOFED_TAG:
            agents = [a for a in agents if a.gps_tag != "patrol-bravo"]
            agents.append(_spoofed(site, rng, dur))
        case Family.CLONED_TAG:
            agents = [a for a in agents if a.gps_tag != "patrol-bravo"]
            agents.append(_cloned(site, rng, dur))
        case Family.ASSET_THEFT:
            agents.append(_asset_theft(site, rng, dur, agents))
    return Scenario(spec=spec, start=start, agents=agents)
