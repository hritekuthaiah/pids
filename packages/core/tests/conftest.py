from __future__ import annotations

import pytest
from helpers import SITE_FILE, GpsFactory, TrackFactory, at, geo

from pids_core.contracts import EntityClass, GpsFix, TrackBatch, VisionTrack
from pids_core.site import Site


@pytest.fixture(scope="session")
def site() -> Site:
    return Site.from_yaml(SITE_FILE)


@pytest.fixture
def track_batch(site: Site) -> TrackFactory:
    def make(
        t: float,
        east: float,
        north: float,
        *,
        track_id: str = "1",
        node_id: str = "edge-01",
        cls: EntityClass = EntityClass.PERSON,
        conf: float = 0.85,
        hits: int = 20,
        thermal: bool | None = True,
        anomaly: float | None = None,
    ) -> TrackBatch:
        return TrackBatch(
            site_id=site.id,
            node_id=node_id,
            captured_at=at(t),
            tracks=[
                VisionTrack(
                    track_id=track_id,
                    entity_class=cls,
                    class_confidence=conf,
                    position=geo(site, east, north),
                    position_sigma_m=1.0,
                    hits=hits,
                    thermal_confirmed=thermal,
                    anomaly_score=anomaly,
                )
            ],
        )

    return make


@pytest.fixture
def gps_fix(site: Site) -> GpsFactory:
    def make(t: float, east: float, north: float, *, tag: str = "patrol-alpha") -> GpsFix:
        return GpsFix(
            site_id=site.id,
            tag_id=tag,
            at=at(t),
            position=geo(site, east, north),
            accuracy_m=3.0,
            hdop=0.9 + 0.01 * (int(t) % 7),
            satellites=9,
        )

    return make
