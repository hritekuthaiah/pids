from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pids_core.contracts import ZoneKind
from pids_core.geo import Enu, LocalFrame, heading_deg
from pids_core.site import Site, SiteConfig

FRAME = LocalFrame(13.262, 77.42)


@given(st.floats(-3000, 3000), st.floats(-3000, 3000))
def test_enu_round_trip_is_sub_millimetre(east: float, north: float) -> None:
    lat, lon = FRAME.to_wgs84(Enu(east, north))
    back = FRAME.to_enu(lat, lon)
    assert back.distance_to(Enu(east, north)) < 1e-3


def test_origin_maps_to_zero() -> None:
    p = FRAME.to_enu(13.262, 77.42)
    assert abs(p.east) < 1e-6
    assert abs(p.north) < 1e-6


@pytest.mark.parametrize(
    ("ve", "vn", "expected"), [(0, 1, 0), (1, 0, 90), (0, -1, 180), (-1, 0, 270)]
)
def test_heading_is_compass_clockwise_from_north(ve: float, vn: float, expected: float) -> None:
    assert heading_deg(ve, vn) == pytest.approx(expected)


def test_invalid_origin_rejected() -> None:
    with pytest.raises(ValueError, match="invalid origin"):
        LocalFrame(95.0, 0.0)


def test_demo_site_loads(site: Site) -> None:
    assert site.id == "site-alpha"
    kinds = {z.kind for z in site.zones}
    assert kinds == {ZoneKind.WARNING, ZoneKind.CRITICAL, ZoneKind.CONTAINMENT}
    assert site.tags["crate-07"].home_zone == "armoury"
    assert not site.tags["badge-0999"].authorized


def _minimal(**overrides: object) -> dict[str, object]:
    cfg: dict[str, object] = {
        "site": {"id": "s1", "name": "S", "origin": {"lat": 10.0, "lon": 10.0}},
        "zones": [
            {
                "id": "core",
                "name": "Core",
                "kind": "critical",
                "polygon": [[0, 0], [10, 0], [10, 10]],
            }
        ],
    }
    cfg.update(overrides)
    return cfg


def test_site_requires_a_critical_zone() -> None:
    cfg = _minimal(
        zones=[{"id": "outer", "name": "W", "kind": "warning", "polygon": [[0, 0], [1, 0], [1, 1]]}]
    )
    with pytest.raises(ValidationError, match="critical zone"):
        SiteConfig.model_validate(cfg)


def test_duplicate_zone_ids_rejected() -> None:
    zone = {
        "id": "core",
        "name": "Core",
        "kind": "critical",
        "polygon": [[0, 0], [10, 0], [10, 10]],
    }
    with pytest.raises(ValidationError, match="unique"):
        SiteConfig.model_validate(_minimal(zones=[zone, zone]))


def test_home_zone_must_be_containment() -> None:
    cfg = _minimal(tags=[{"id": "a", "label": "A", "kind": "asset", "home_zone": "core"}])
    with pytest.raises(ValidationError, match="not a containment zone"):
        SiteConfig.model_validate(cfg)


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        SiteConfig.model_validate(_minimal(surprise=True))
