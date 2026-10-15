"""Sensor models: render true agent positions into the messages real sensors emit.

Camera (post-tracker, i.e. what the edge node publishes):
  * detection only inside a node's field-of-view sector; probability falls with range;
  * localisation error grows with range (ground-plane homography error);
  * per-frame class confusion (dogs read as people, people as animals) with
    confidence drawn lower when the class is wrong;
  * tracks confirm after 2 hits, die after ~3 s unseen (re-acquisition = new ID),
    and occasionally switch ID;
  * short-lived low-confidence ghost tracks (foliage, birds, glare).
Thermal: heat present/absent only inside the thermal sector; ``None`` outside.
GPS tags: 1 Hz fixes with noise, jittering quality and dropouts; spoofed tags
report a different trajectory from the one their carrier walks.
RFID: reads when a badge passes within range of a fixed reader.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from shapely.geometry import Point
from shapely.prepared import PreparedGeometry, prep

from pids_core.contracts import EntityClass, GeoPoint, GpsFix, TagRead, TrackBatch, VisionTrack
from pids_core.coverage import sector
from pids_core.geo import Enu
from pids_core.site import NodeConfig, Site
from pids_sim.agents import Agent

_CLASSES = [EntityClass.PERSON, EntityClass.VEHICLE, EntityClass.ANIMAL]
_CONFUSION = {
    EntityClass.PERSON: [0.92, 0.03, 0.05],
    EntityClass.VEHICLE: [0.05, 0.95, 0.00],
    EntityClass.ANIMAL: [0.12, 0.03, 0.85],
}


@dataclass(frozen=True, slots=True)
class SensorParams:
    frame_dt: float = 0.5
    pd_near: float = 0.97
    pd_far: float = 0.65
    sigma_base_m: float = 0.5
    sigma_per_m: float = 0.015
    confirm_hits: int = 2
    max_missed_s: float = 3.0
    id_switch_per_frame: float = 0.002
    ghost_rate_per_s: float = 1.0 / 120.0
    thermal_pd: float = 0.9
    thermal_false_heat: float = 0.05
    gps_sigma_m: float = 3.0
    gps_dropout: float = 0.03
    rfid_period_s: float = 2.0


@dataclass(frozen=True, slots=True)
class Frame:
    t: float
    at: datetime
    batches: list[TrackBatch]
    fixes: list[GpsFix]
    reads: list[TagRead]


@dataclass(slots=True)
class _Track:
    track_id: str
    hits: int = 0
    last_seen: float = -math.inf


@dataclass(slots=True)
class _Ghost:
    track_id: str
    east: float
    north: float
    until: float
    cls: EntityClass
    conf: float
    hits: int = 0


@dataclass(slots=True)
class _Node:
    cfg: NodeConfig
    fov: PreparedGeometry
    thermal: PreparedGeometry | None
    next_id: int = 1
    tracks: dict[str, _Track] = field(default_factory=dict)
    ghosts: list[_Ghost] = field(default_factory=list)

    def new_id(self) -> str:
        self.next_id += 1
        return str(self.next_id - 1)


class Renderer:
    """Steps the world forward and produces sensor messages for each frame."""

    def __init__(
        self,
        site: Site,
        agents: list[Agent],
        rng: np.random.Generator,
        start: datetime,
        params: SensorParams | None = None,
    ) -> None:
        self.site = site
        self.agents = agents
        self.rng = rng
        self.start = start
        self.p = params or SensorParams()
        self.entity_agent: dict[str, str | None] = {}
        self._nodes = [
            _Node(
                cfg=n,
                fov=prep(sector(n.position, n.heading_deg, n.fov_deg, n.range_m)),
                thermal=prep(
                    sector(n.position, n.heading_deg, n.thermal.fov_deg, n.thermal.range_m)
                )
                if n.thermal
                else None,
            )
            for n in site.config.nodes
        ]
        self._next_fix: dict[str, float] = {}
        self._last_read: dict[str, float] = {}

    # ------------------------------------------------------------------ frame

    def frame(self, t: float) -> Frame:
        at = self.start + timedelta(seconds=t)
        batches = [self._camera(node, t, at) for node in self._nodes]
        return Frame(
            t=t,
            at=at,
            batches=[b for b in batches if b.tracks],
            fixes=self._gps(t, at),
            reads=self._rfid(t, at),
        )

    def _geo(self, e: float, n: float) -> GeoPoint:
        lat, lon = self.site.frame.to_wgs84(Enu(e, n))
        return GeoPoint(lat=lat, lon=lon)

    # ----------------------------------------------------------------- camera

    def _thermal(self, node: _Node, e: float, n: float, warm: bool) -> bool | None:
        if node.thermal is None or not node.thermal.contains(Point(e, n)):
            return None
        p = self.p.thermal_pd if warm else self.p.thermal_false_heat
        return bool(self.rng.random() < p)

    def _camera(self, node: _Node, t: float, at: datetime) -> TrackBatch:
        rng, p = self.rng, self.p
        ox, oy = node.cfg.position
        out: list[VisionTrack] = []
        for agent in self.agents:
            pos = agent.trajectory.at(t)
            if (
                pos is None
                or not agent.visible
                or not node.fov.contains(Point(pos.east, pos.north))
            ):
                continue
            r = math.hypot(pos.east - ox, pos.north - oy)
            frac = min(r / node.cfg.range_m, 1.0)
            if rng.random() > p.pd_near - (p.pd_near - p.pd_far) * frac**2:
                continue
            key = agent.id
            tr = node.tracks.get(key)
            if (
                tr is None
                or t - tr.last_seen > p.max_missed_s
                or rng.random() < p.id_switch_per_frame
            ):
                tr = _Track(track_id=node.new_id())
                node.tracks[key] = tr
                self.entity_agent[f"{node.cfg.id}/{tr.track_id}"] = agent.id
            tr.hits += 1
            tr.last_seen = t
            if tr.hits < p.confirm_hits:
                continue
            sigma = p.sigma_base_m + p.sigma_per_m * r
            cls_idx = rng.choice(3, p=_CONFUSION[agent.entity_class])
            cls = _CLASSES[int(cls_idx)]
            conf = rng.beta(8, 2) if cls is agent.entity_class else rng.beta(3, 4)
            conf *= 1.0 - 0.3 * frac**2
            e = pos.east + rng.normal(0, sigma)
            n = pos.north + rng.normal(0, sigma)
            out.append(
                VisionTrack(
                    track_id=tr.track_id,
                    entity_class=cls,
                    class_confidence=float(np.clip(conf, 0.01, 0.99)),
                    position=self._geo(e, n),
                    position_sigma_m=sigma,
                    hits=tr.hits,
                    thermal_confirmed=self._thermal(node, e, n, agent.warm),
                )
            )
        out.extend(self._ghosts(node, t))
        return TrackBatch(
            site_id=self.site.id,
            node_id=node.cfg.id,
            captured_at=at,
            tracks=out,
            trace={"captured": at},
        )

    def _ghosts(self, node: _Node, t: float) -> list[VisionTrack]:
        rng, p = self.rng, self.p
        node.ghosts = [g for g in node.ghosts if g.until >= t]
        if rng.random() < p.ghost_rate_per_s * p.frame_dt:
            ox, oy = node.cfg.position
            bearing = math.radians(
                node.cfg.heading_deg + rng.uniform(-0.45, 0.45) * node.cfg.fov_deg
            )
            r = rng.uniform(15, node.cfg.range_m)
            g = _Ghost(
                track_id=node.new_id(),
                east=ox + r * math.sin(bearing),
                north=oy + r * math.cos(bearing),
                until=t + rng.uniform(1.0, 3.5),
                cls=EntityClass.PERSON if rng.random() < 0.5 else EntityClass.ANIMAL,
                conf=float(rng.uniform(0.3, 0.55)),
            )
            node.ghosts.append(g)
            self.entity_agent[f"{node.cfg.id}/{g.track_id}"] = None
        out = []
        for g in node.ghosts:
            g.hits += 1
            g.east += rng.normal(0, 0.3)
            g.north += rng.normal(0, 0.3)
            out.append(
                VisionTrack(
                    track_id=g.track_id,
                    entity_class=g.cls,
                    class_confidence=g.conf,
                    position=self._geo(g.east, g.north),
                    position_sigma_m=1.5,
                    hits=g.hits,
                    thermal_confirmed=self._thermal(node, g.east, g.north, warm=False),
                )
            )
        return out

    # -------------------------------------------------------------------- GPS

    def _gps(self, t: float, at: datetime) -> list[GpsFix]:
        rng, p = self.rng, self.p
        fixes = []
        for agent in self.agents:
            if agent.gps_tag is None:
                continue
            traj = agent.reported_trajectory or agent.trajectory
            pos = traj.at(t)
            if pos is None:
                continue
            due = self._next_fix.get(agent.id, traj.start)
            if t < due:
                continue
            self._next_fix[agent.id] = t + agent.gps_period_s
            if rng.random() < p.gps_dropout:
                continue
            self.entity_agent[f"tag/{agent.gps_tag}"] = agent.id
            fixes.append(
                GpsFix(
                    site_id=self.site.id,
                    tag_id=agent.gps_tag,
                    at=at,
                    position=self._geo(
                        pos.east + rng.normal(0, p.gps_sigma_m),
                        pos.north + rng.normal(0, p.gps_sigma_m),
                    ),
                    accuracy_m=float(rng.uniform(2.5, 4.5)),
                    hdop=float(rng.uniform(0.7, 1.4)),
                    satellites=int(rng.integers(7, 13)),
                    trace={"captured": at},
                )
            )
        return fixes

    # ------------------------------------------------------------------- RFID

    def _rfid(self, t: float, at: datetime) -> list[TagRead]:
        reads = []
        for agent in self.agents:
            if agent.rfid_tag is None:
                continue
            pos = agent.trajectory.at(t)
            if pos is None:
                continue
            for reader in self.site.config.readers:
                if pos.distance_to(Enu(*reader.position)) > reader.range_m:
                    continue
                if t - self._last_read.get(agent.id, -math.inf) < self.p.rfid_period_s:
                    continue
                self._last_read[agent.id] = t
                reads.append(
                    TagRead(
                        site_id=self.site.id,
                        reader_id=reader.id,
                        tag_id=agent.rfid_tag,
                        at=at,
                        trace={"captured": at},
                    )
                )
        return reads
