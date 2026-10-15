"""Nested-zone geofencing (PLT-01).

Zones are polygons in the site's ENU frame. Exclusion zones nest — an outer
*warning* ring around an inner *critical* core — and a point's zone is the most
severe zone that contains it. *Containment* zones are evaluated separately: they
home tagged assets, and the event of interest is an asset being **outside** its
home zone.

Besides membership, the decision layer needs *how far* an entity is from a
boundary and *how soon* it will reach one at its current velocity; both are
answered here so features, forecasting and scoring share one geometry.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.prepared import PreparedGeometry, prep

from pids_core.contracts import ZoneKind
from pids_core.geo import Enu

_SEVERITY = {ZoneKind.WARNING: 1, ZoneKind.CRITICAL: 2}


@dataclass(frozen=True, slots=True)
class Zone:
    id: str
    name: str
    kind: ZoneKind
    polygon: Polygon

    def __post_init__(self) -> None:
        if not self.polygon.is_valid or self.polygon.is_empty:
            raise ValueError(f"zone {self.id!r} has an invalid or empty polygon")

    @property
    def severity(self) -> int:
        return _SEVERITY.get(self.kind, 0)


@dataclass(frozen=True, slots=True)
class ZoneHit:
    """Exclusion-zone membership for one point."""

    zone: Zone | None
    containing: tuple[Zone, ...]

    @property
    def kind(self) -> ZoneKind | None:
        return self.zone.kind if self.zone else None


@dataclass(frozen=True, slots=True)
class PredictedEntry:
    zone: Zone
    seconds: float
    distance_m: float


class ZoneIndex:
    """Fast spatial queries over a site's zones (prepared geometries, ENU metres)."""

    def __init__(self, zones: Iterable[Zone]) -> None:
        self._zones: dict[str, Zone] = {}
        for zone in zones:
            if zone.id in self._zones:
                raise ValueError(f"duplicate zone id {zone.id!r}")
            self._zones[zone.id] = zone
        # Most severe first so `locate` can return the first hit.
        self._exclusion: list[Zone] = sorted(
            (z for z in self._zones.values() if z.kind is not ZoneKind.CONTAINMENT),
            key=lambda z: -z.severity,
        )
        self._prepared: dict[str, PreparedGeometry] = {
            zid: prep(z.polygon) for zid, z in self._zones.items()
        }

    def __getitem__(self, zone_id: str) -> Zone:
        return self._zones[zone_id]

    def __iter__(self) -> Iterator[Zone]:
        return iter(self._zones.values())

    @property
    def zones(self) -> Sequence[Zone]:
        return list(self._zones.values())

    def of_kind(self, kind: ZoneKind) -> list[Zone]:
        return [z for z in self._zones.values() if z.kind is kind]

    # -- membership ---------------------------------------------------------

    def contains(self, zone_id: str, p: Enu) -> bool:
        return bool(self._prepared[zone_id].contains(Point(p.east, p.north)))

    def locate(self, p: Enu) -> ZoneHit:
        """Most severe exclusion zone containing ``p`` (``zone=None`` when outside all)."""
        pt = Point(p.east, p.north)
        containing = tuple(z for z in self._exclusion if self._prepared[z.id].contains(pt))
        return ZoneHit(zone=containing[0] if containing else None, containing=containing)

    # -- distances ----------------------------------------------------------

    def signed_distance(self, zone_id: str, p: Enu) -> float:
        """Distance to the zone boundary in metres: negative inside, positive outside."""
        zone = self._zones[zone_id]
        pt = Point(p.east, p.north)
        d = float(zone.polygon.exterior.distance(pt))
        return -d if self._prepared[zone_id].contains(pt) else d

    def distance_to_kind(self, kind: ZoneKind, p: Enu) -> float:
        """Signed distance to the nearest zone of ``kind`` (``inf`` if the site has none)."""
        zones = self.of_kind(kind)
        if not zones:
            return math.inf
        return min(self.signed_distance(z.id, p) for z in zones)

    def boundary_tangent(self, zone_id: str, p: Enu) -> tuple[float, float]:
        """Unit tangent of the zone boundary at the point nearest ``p``."""
        ring = self._zones[zone_id].polygon.exterior
        s = ring.project(Point(p.east, p.north))
        a = ring.interpolate(max(s - 0.5, 0.0))
        b = ring.interpolate(min(s + 0.5, ring.length))
        dx, dy = b.x - a.x, b.y - a.y
        norm = math.hypot(dx, dy) or 1.0
        return dx / norm, dy / norm

    # -- forecasting --------------------------------------------------------

    def predict_entry(
        self,
        kind: ZoneKind,
        p: Enu,
        velocity: tuple[float, float],
        horizon_s: float,
        min_speed: float = 0.2,
    ) -> PredictedEntry | None:
        """Earliest entry into a zone of ``kind`` along a constant-velocity path.

        Returns None when already inside such a zone, effectively stationary, or
        not reaching one within ``horizon_s`` seconds.
        """
        ve, vn = velocity
        speed = math.hypot(ve, vn)
        if speed < min_speed:
            return None
        start = (p.east, p.north)
        end = (p.east + ve * horizon_s, p.north + vn * horizon_s)
        path = LineString([start, end])
        best: PredictedEntry | None = None
        for zone in self.of_kind(kind):
            if self._prepared[zone.id].contains(Point(start)):
                return None
            if not self._prepared[zone.id].intersects(path):
                continue
            crossing = zone.polygon.boundary.intersection(path)
            coords = shapely.get_coordinates(crossing)
            if len(coords) == 0:
                continue
            dist = min(float(path.project(Point(c))) for c in coords)
            if best is None or dist < best.distance_m:
                best = PredictedEntry(zone=zone, seconds=dist / speed, distance_m=dist)
        return best


def polygon_from_points(points: Sequence[Sequence[float]]) -> Polygon:
    if len(points) < 3:
        raise ValueError("a zone polygon needs at least three vertices")
    poly = Polygon([(float(x), float(y)) for x, y in points])
    if not poly.is_valid:
        poly = shapely.make_valid(poly)
        if not isinstance(poly, Polygon):
            raise ValueError("zone polygon is self-intersecting and cannot be repaired")
    return poly
