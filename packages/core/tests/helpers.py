"""Shared test helpers (importable; fixtures live in conftest.py)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pids_core.contracts import GeoPoint, GpsFix, TrackBatch
from pids_core.geo import Enu
from pids_core.site import Site

SITE_FILE = Path(__file__).resolve().parents[3] / "config" / "sites" / "site-alpha.yaml"
T0 = datetime(2026, 10, 27, 4, 30, tzinfo=UTC)  # 10:00 IST on demo day

TrackFactory = Callable[..., TrackBatch]
GpsFactory = Callable[..., GpsFix]


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def geo(site: Site, east: float, north: float) -> GeoPoint:
    lat, lon = site.frame.to_wgs84(Enu(east, north))
    return GeoPoint(lat=lat, lon=lon)
