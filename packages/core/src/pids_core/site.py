"""Site definition: the single source of truth for a protected site's geometry.

A site file (YAML) declares the origin, the nested zones, sensor nodes, tag
readers, authorised tags, and descriptive features (roads, patrol routes) that
the simulator and the dashboard draw. Geometry is written in **local metres**
(east, north) because that is what a person surveying a site can reason about;
it is converted to WGS84 on demand for storage and maps.

The server seeds PostGIS from this file, the simulator and the evaluation
harness read it directly — so all three always agree on the geometry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pids_core.contracts import TagKind, ThreatLevel, ZoneKind
from pids_core.geo import Enu, LocalFrame
from pids_core.geofence import Zone, ZoneIndex, polygon_from_points

XY = tuple[float, float]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OriginConfig(_Config):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]


class SiteInfo(_Config):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
    name: str
    origin: OriginConfig
    timezone: str = "UTC"


class ZoneConfig(_Config):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
    name: str
    kind: ZoneKind
    polygon: list[XY] = Field(min_length=3, description="vertices in local metres (east, north)")
    actions: dict[ThreatLevel, list[str]] = Field(default_factory=dict)


class ThermalConfig(_Config):
    fov_deg: Annotated[float, Field(gt=0, le=360)] = 55.0
    range_m: Annotated[float, Field(gt=0)] = 60.0


class NodeConfig(_Config):
    """A sensor node (camera, optionally with a co-located thermal array)."""

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
    position: XY
    heading_deg: Annotated[float, Field(ge=0, lt=360)]
    fov_deg: Annotated[float, Field(gt=0, le=360)] = 90.0
    range_m: Annotated[float, Field(gt=0)] = 150.0
    thermal: ThermalConfig | None = None


class ReaderConfig(_Config):
    """A fixed short-range RFID/BLE reader (e.g. at a gate)."""

    id: str
    position: XY
    range_m: Annotated[float, Field(gt=0)] = 4.0


class TagConfig(_Config):
    id: str
    label: str
    kind: TagKind
    authorized: bool = True
    home_zone: str | None = Field(
        default=None, description="containment zone an asset must stay in"
    )


class FeaturesConfig(_Config):
    roads: dict[str, list[XY]] = Field(default_factory=dict)
    patrol_routes: dict[str, list[XY]] = Field(default_factory=dict)
    gates: dict[str, XY] = Field(default_factory=dict)


class SiteConfig(_Config):
    site: SiteInfo
    zones: list[ZoneConfig] = Field(min_length=1)
    nodes: list[NodeConfig] = Field(default_factory=list)
    readers: list[ReaderConfig] = Field(default_factory=list)
    tags: list[TagConfig] = Field(default_factory=list)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)

    @field_validator("zones")
    @classmethod
    def _unique_zone_ids(cls, zones: list[ZoneConfig]) -> list[ZoneConfig]:
        ids = [z.id for z in zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone ids must be unique")
        return zones

    @model_validator(mode="after")
    def _check_references(self) -> SiteConfig:
        containment = {z.id for z in self.zones if z.kind is ZoneKind.CONTAINMENT}
        for tag in self.tags:
            if tag.home_zone is not None and tag.home_zone not in containment:
                raise ValueError(
                    f"tag {tag.id!r}: home_zone {tag.home_zone!r} is not a containment zone"
                )
        if not any(z.kind is ZoneKind.CRITICAL for z in self.zones):
            raise ValueError("a site needs at least one critical zone")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> SiteConfig:
        raw: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)


class Site:
    """A loaded site: frame, zone index and registries, ready for the decision core."""

    def __init__(self, config: SiteConfig) -> None:
        self.config = config
        self.id = config.site.id
        self.frame = LocalFrame(config.site.origin.lat, config.site.origin.lon)
        self.zones = ZoneIndex(
            Zone(id=z.id, name=z.name, kind=z.kind, polygon=polygon_from_points(z.polygon))
            for z in config.zones
        )
        self.tags: dict[str, TagConfig] = {t.id: t for t in config.tags}
        self.nodes: dict[str, NodeConfig] = {n.id: n for n in config.nodes}
        self.readers: dict[str, ReaderConfig] = {r.id: r for r in config.readers}

    @classmethod
    def from_yaml(cls, path: str | Path) -> Site:
        return cls(SiteConfig.from_yaml(path))

    def zone_config(self, zone_id: str) -> ZoneConfig:
        return next(z for z in self.config.zones if z.id == zone_id)

    def to_wgs84_ring(self, points: list[XY]) -> list[tuple[float, float]]:
        """Local-metre vertices -> ``[(lat, lon), ...]`` closed ring."""
        ring = [self.frame.to_wgs84(Enu(e, n)) for e, n in points]
        if ring and ring[0] != ring[-1]:
            ring.append(ring[0])
        return ring
