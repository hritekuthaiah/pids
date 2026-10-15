from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from shapely.geometry import Polygon

from pids_core.contracts import ZoneKind
from pids_core.geo import Enu
from pids_core.geofence import Zone, ZoneIndex, polygon_from_points
from pids_core.site import Site

SQUARE = [(-100.0, -100.0), (100.0, -100.0), (100.0, 100.0), (-100.0, 100.0)]
RING = [(-200.0, -200.0), (200.0, -200.0), (200.0, 200.0), (-200.0, 200.0)]


@pytest.fixture
def index() -> ZoneIndex:
    return ZoneIndex(
        [
            Zone("outer", "Outer", ZoneKind.WARNING, Polygon(RING)),
            Zone("core", "Core", ZoneKind.CRITICAL, Polygon(SQUARE)),
            Zone(
                "vault",
                "Vault",
                ZoneKind.CONTAINMENT,
                Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
            ),
        ]
    )


def test_most_severe_zone_wins(index: ZoneIndex) -> None:
    hit = index.locate(Enu(5, 5))
    assert hit.zone is not None
    assert hit.zone.id == "core"
    assert [z.id for z in hit.containing] == ["core", "outer"]


def test_warning_ring_and_outside(index: ZoneIndex) -> None:
    assert index.locate(Enu(150, 0)).kind is ZoneKind.WARNING
    outside = index.locate(Enu(500, 0))
    assert outside.zone is None
    assert outside.kind is None


def test_containment_zones_never_returned_by_locate(index: ZoneIndex) -> None:
    hit = index.locate(Enu(5, 5))
    assert all(z.kind is not ZoneKind.CONTAINMENT for z in hit.containing)
    assert index.contains("vault", Enu(5, 5))


@given(st.floats(-300, 300), st.floats(-300, 300))
def test_signed_distance_sign_matches_membership(e: float, n: float) -> None:
    index = ZoneIndex([Zone("core", "Core", ZoneKind.CRITICAL, Polygon(SQUARE))])
    d = index.signed_distance("core", Enu(e, n))
    inside = index.contains("core", Enu(e, n))
    if inside:
        assert d <= 0
    else:
        assert d >= 0
    expected = max(abs(e), abs(n)) - 100 if not inside else -(100 - max(abs(e), abs(n)))
    if abs(e) <= 100 or abs(n) <= 100:
        assert d == pytest.approx(expected, abs=1e-6)


def test_predict_entry_head_on(index: ZoneIndex) -> None:
    entry = index.predict_entry(ZoneKind.CRITICAL, Enu(0, 160), (0.0, -2.0), horizon_s=60)
    assert entry is not None
    assert entry.zone.id == "core"
    assert entry.seconds == pytest.approx(30.0)
    assert entry.distance_m == pytest.approx(60.0)


@pytest.mark.parametrize(
    ("start", "velocity"),
    [
        ((0.0, 160.0), (0.0, 2.0)),  # moving away
        ((0.0, 160.0), (0.0, 0.05)),  # effectively stationary
        ((0.0, 500.0), (0.0, -2.0)),  # too far for the horizon
        ((0.0, 0.0), (0.0, -2.0)),  # already inside
        ((0.0, 160.0), (2.0, 0.0)),  # moving parallel, never enters
    ],
)
def test_predict_entry_none(
    index: ZoneIndex, start: tuple[float, float], velocity: tuple[float, float]
) -> None:
    assert index.predict_entry(ZoneKind.CRITICAL, Enu(*start), velocity, horizon_s=60) is None


def test_boundary_tangent_along_top_edge(index: ZoneIndex) -> None:
    tx, ty = index.boundary_tangent("core", Enu(10, 120))
    assert abs(tx) == pytest.approx(1.0)
    assert ty == pytest.approx(0.0, abs=1e-9)


def test_distance_to_missing_kind_is_infinite() -> None:
    index = ZoneIndex([Zone("core", "Core", ZoneKind.CRITICAL, Polygon(SQUARE))])
    assert math.isinf(index.distance_to_kind(ZoneKind.WARNING, Enu(0, 0)))


def test_duplicate_zone_rejected() -> None:
    z = Zone("core", "Core", ZoneKind.CRITICAL, Polygon(SQUARE))
    with pytest.raises(ValueError, match="duplicate"):
        ZoneIndex([z, z])


def test_polygon_validation() -> None:
    with pytest.raises(ValueError, match="three"):
        polygon_from_points([(0, 0), (1, 1)])
    with pytest.raises(ValueError, match="self-intersecting"):
        polygon_from_points([(0, 0), (10, 10), (10, 0), (0, 10)])


def test_demo_site_geometry(site: Site) -> None:
    zones = site.zones
    assert zones.locate(Enu(0, 0)).kind is ZoneKind.CRITICAL
    assert zones.locate(Enu(0, 160)).kind is ZoneKind.WARNING
    assert zones.locate(Enu(0, 400)).kind is None
    # the public road runs through the warning band
    assert zones.locate(Enu(0, -178)).kind is ZoneKind.WARNING
