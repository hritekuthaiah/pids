"""Coordinate frames.

Storage, GPS and maps use WGS84 latitude/longitude. Every kinematic quantity —
speed, distance to a fence, Kalman state, behavioural features — is computed in a
local East-North frame in metres centred on the site origin, using an azimuthal
equidistant projection. Within a few kilometres of the origin the distortion is
millimetres, far below GPS or vision localisation error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pyproj import CRS, Transformer


@dataclass(frozen=True, slots=True)
class Enu:
    """A point in the site's local frame: metres east and north of the origin."""

    east: float
    north: float

    def distance_to(self, other: Enu) -> float:
        return math.hypot(self.east - other.east, self.north - other.north)


@dataclass(frozen=True, slots=True)
class LocalFrame:
    """Bidirectional WGS84 <-> local ENU conversion for one site."""

    origin_lat: float
    origin_lon: float
    _to_enu: Transformer = field(init=False, repr=False, compare=False)
    _to_wgs: Transformer = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not (-90.0 <= self.origin_lat <= 90.0 and -180.0 <= self.origin_lon <= 180.0):
            raise ValueError(f"invalid origin {self.origin_lat}, {self.origin_lon}")
        local = CRS.from_proj4(
            f"+proj=aeqd +lat_0={self.origin_lat} +lon_0={self.origin_lon} "
            "+datum=WGS84 +units=m +no_defs"
        )
        wgs84 = CRS.from_epsg(4326)
        object.__setattr__(self, "_to_enu", Transformer.from_crs(wgs84, local, always_xy=True))
        object.__setattr__(self, "_to_wgs", Transformer.from_crs(local, wgs84, always_xy=True))

    def to_enu(self, lat: float, lon: float) -> Enu:
        east, north = self._to_enu.transform(lon, lat)
        return Enu(float(east), float(north))

    def to_wgs84(self, point: Enu) -> tuple[float, float]:
        """Return ``(lat, lon)``."""
        lon, lat = self._to_wgs.transform(point.east, point.north)
        return float(lat), float(lon)


def heading_deg(ve: float, vn: float) -> float:
    """Compass heading of a velocity vector, degrees clockwise from north in [0, 360)."""
    return math.degrees(math.atan2(ve, vn)) % 360.0
