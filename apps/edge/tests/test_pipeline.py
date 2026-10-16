"""End-to-end perception: synthetic people through a known camera -> TrackBatch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from edge_helpers import DEMO_SITE, dets, frame, person_box, true_calibration
from pids_core.contracts import EntityClass, TrackBatch
from pids_core.site import Site
from pids_edge.config import EdgeConfig, GroundConfig
from pids_edge.detector import Detections
from pids_edge.ground import GroundPlane
from pids_edge.pipeline import Annotator, EdgeNode, Rates


class Scripted:
    """A 'detector' that reports where the synthetic people are in each frame."""

    def __init__(self, paths: list[list[tuple[float, float]]]) -> None:
        self.paths = paths
        self.last_inference_ms = 4.0

    def __call__(self, image: np.ndarray) -> Detections:
        del image
        k = self.k
        boxes = [person_box(*p[k]) for p in self.paths if k < len(p)]
        return dets(boxes, [0.88] * len(boxes))


def _node(paths: list[list[tuple[float, float]]]) -> tuple[EdgeNode, Scripted]:
    site = Site.from_yaml(DEMO_SITE)
    cfg = EdgeConfig(
        site=DEMO_SITE, node_id="edge-01", ground=GroundConfig(calibration=Path("unused"))
    )
    det = Scripted(paths)
    return EdgeNode(cfg, site, det, GroundPlane(true_calibration()), boot="00042"), det


def _walk(a: tuple[float, float], b: tuple[float, float], n: int) -> list[tuple[float, float]]:
    return [
        (a[0] + (b[0] - a[0]) * i / (n - 1), a[1] + (b[1] - a[1]) * i / (n - 1)) for i in range(n)
    ]


def _process(node: EdgeNode, det: Scripted, k: int) -> TrackBatch:
    det.k = k
    batch, _ = node.process(frame(k))
    return batch


def test_people_are_published_where_they_stand() -> None:
    path = _walk((2.5, 1.5), (6.5, 2.5), 40)
    node, det = _node([path])
    site = node.site
    for k in range(40):
        batch = _process(node, det, k)
        assert batch.site_id == "demo-room"
        assert batch.node_id == "edge-01"
        if k == 0:
            continue
        (tr,) = batch.tracks
        assert tr.track_id == "00042-1"
        assert tr.entity_class is EntityClass.PERSON
        assert tr.hits == k + 1
        here = site.frame.to_enu(tr.position.lat, tr.position.lon)
        # the Kalman-smoothed box lags a moving person slightly; well inside sigma
        assert here.distance_to(type(here)(*path[k])) < 0.15
        assert 0.02 < tr.position_sigma_m < 0.6
        assert {"captured", "perceived"} <= set(batch.trace)


def test_two_people_get_two_stable_ids() -> None:
    a = _walk((2.5, 1.0), (7.0, 1.5), 50)
    b = _walk((6.5, 4.5), (2.0, 2.0), 50)
    node, det = _node([a, b])
    seen: set[str] = set()
    for k in range(50):
        seen |= {t.track_id for t in _process(node, det, k).tracks}
    assert seen == {"00042-1", "00042-2"}


def test_projections_beyond_the_node_range_are_dropped() -> None:
    node, det = _node([[(40.0, -30.0)] * 5])
    for k in range(5):
        assert _process(node, det, k).tracks == []


def test_unknown_node_is_a_configuration_error() -> None:
    site = Site.from_yaml(DEMO_SITE)
    cfg = EdgeConfig(site=DEMO_SITE, node_id="edge-99", ground=GroundConfig(calibration=Path("x")))
    with pytest.raises(ValueError, match="edge-99"):
        EdgeNode(cfg, site, Scripted([]), GroundPlane(true_calibration()))


def test_annotator_draws_zones_and_tracks() -> None:
    node, det = _node([_walk((2.0, 2.0), (3.0, 2.0), 3)])
    for k in range(3):
        det.k = k
        _, observed = node.process(frame(k))
    img = frame(0).image
    out = Annotator(node.site, node.ground, "edge-01").draw(img, observed, Rates())
    assert out.shape == img.shape
    assert out.any()  # something was drawn
    assert not img.any()  # on a copy


def test_rates_smooth_fps() -> None:
    r = Rates()
    for k in range(50):
        r.tick(k * 0.1, 10.0)
    assert r.fps == pytest.approx(10.0, rel=0.01)
    assert r.inference_ms == pytest.approx(10.0)


def test_edge_config_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="low_threshold"):
        EdgeConfig.model_validate(
            {
                "site": str(DEMO_SITE),
                "node_id": "edge-01",
                "ground": {"calibration": "x"},
                "tracker": {"low_threshold": 0.6, "high_threshold": 0.5},
            }
        )
