"""Sensor coverage geometry: which ground a camera / thermal array can see.

Used to decide whether the *absence* of a detection is evidence: a GPS tag that
claims to be inside a camera's field of view while the camera sees nobody there
is suspicious (spoofing check), whereas the same tag outside every field of view
says nothing either way.
"""

from __future__ import annotations

import math

from shapely.geometry import Point, Polygon
from shapely.prepared import PreparedGeometry, prep

from pids_core.geo import Enu


def sector(
    origin: tuple[float, float], heading_deg: float, fov_deg: float, range_m: float
) -> Polygon:
    """Field-of-view sector polygon in ENU metres (heading clockwise from north)."""
    ox, oy = origin
    if fov_deg >= 360.0:
        return Point(ox, oy).buffer(range_m, quad_segs=32)
    steps = max(8, int(fov_deg / 3))
    start = heading_deg - fov_deg / 2.0
    pts = [(ox, oy)]
    for i in range(steps + 1):
        bearing = math.radians(start + fov_deg * i / steps)
        pts.append((ox + range_m * math.sin(bearing), oy + range_m * math.cos(bearing)))
    return Polygon(pts)


class Coverage:
    """Union-free set of coverage sectors with fast point queries."""

    def __init__(self, sectors: dict[str, Polygon]) -> None:
        self.sectors = sectors
        self._prepared: dict[str, PreparedGeometry] = {k: prep(v) for k, v in sectors.items()}

    def covering(self, p: Enu) -> list[str]:
        pt = Point(p.east, p.north)
        return [k for k, g in self._prepared.items() if g.contains(pt)]

    def covers(self, p: Enu) -> bool:
        return bool(self.covering(p))
