"""Floor homography: fitting, projection, uncertainty and calibration files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from edge_helpers import SIZE, person_box, project, true_calibration
from pids_edge.ground import Calibration, GroundPlane, apply, fit


def test_pose_homography_round_trips_floor_points() -> None:
    ground = GroundPlane(true_calibration())
    for e, n in [(1.5, 1.0), (4.0, 3.0), (7.0, 1.0), (6.5, 4.5)]:
        u, v = project(e, n)
        here = ground.to_world(u, v)
        assert here is not None
        assert (here.east, here.north) == pytest.approx((e, n), abs=1e-6)
        back = ground.to_image(e, n)
        assert back == pytest.approx((u, v), abs=1e-6)


def test_pixels_above_the_horizon_do_not_project() -> None:
    ground = GroundPlane(true_calibration())
    # Tilted 28 degrees down, this camera's horizon is 126 px above the frame; a
    # pixel beyond it must not "project" to a mirrored point behind the camera.
    assert ground.to_world(640, -300) is None
    assert ground.to_world(640, 0) is not None  # the top row is still floor, ~18 m out


def test_fit_recovers_the_homography_from_noisy_clicks() -> None:
    rng = np.random.default_rng(3)
    world = np.array([[1.5, 1.0], [4.0, 1.0], [7.0, 1.0], [7.0, 4.5], [4.0, 4.5], [2.0, 3.0]])
    pixels = np.array([project(e, n) for e, n in world]) + rng.normal(0, 1.0, (6, 2))
    h, rms = fit(pixels, world)
    assert rms < 0.05
    truth = GroundPlane(true_calibration())
    probe = np.array([[5.0, 2.0]])
    u, v = project(5.0, 2.0)
    est = apply(h, np.array([[u, v]]))
    assert np.linalg.norm(est - probe) < 0.06
    assert truth.to_world(u, v) is not None


def test_ransac_rejects_one_misclicked_mark() -> None:
    world = np.array(
        [[1.5, 1.0], [4.0, 1.0], [7.0, 1.0], [7.0, 4.5], [4.0, 4.5], [2.0, 3.0], [5.5, 2.5]]
    )
    pixels = np.array([project(e, n) for e, n in world])
    pixels[3] += [80.0, -40.0]  # clicked the wrong tape cross
    h, _ = fit(pixels, world)
    good = np.delete(np.arange(7), 3)
    assert np.linalg.norm(apply(h, pixels[good]) - world[good], axis=1).max() < 0.01


def test_fit_rejects_too_few_or_collinear_points() -> None:
    with pytest.raises(ValueError, match="at least 4"):
        fit(np.zeros((3, 2)), np.zeros((3, 2)))
    line = np.array([[float(i), 0.0] for i in range(5)])
    with pytest.raises(ValueError, match="degenerate"):
        fit(np.array([project(e, n) for e, n in line]), line)


def test_feet_locate_the_person_and_sigma_grows_with_distance() -> None:
    ground = GroundPlane(true_calibration())
    near = ground.locate(person_box(2.0, 4.0))
    far = ground.locate(person_box(7.5, 0.5))
    assert near is not None
    assert far is not None
    assert (near.position.east, near.position.north) == pytest.approx((2.0, 4.0), abs=1e-3)
    assert (far.position.east, far.position.north) == pytest.approx((7.5, 0.5), abs=1e-3)
    assert near.feet_visible
    assert far.sigma_m > near.sigma_m
    assert 0.02 < near.sigma_m < 0.5


def test_cut_off_feet_are_flagged_and_less_certain() -> None:
    ground = GroundPlane(true_calibration())
    box = person_box(3.0, 2.0)
    clipped = box.copy()
    clipped[3] = SIZE[1] - 1
    seen = ground.locate(box)
    cut = ground.locate(clipped)
    assert seen is not None
    assert cut is not None
    assert not cut.feet_visible
    assert cut.sigma_m > seen.sigma_m


def test_a_lower_resolution_stream_reuses_the_calibration() -> None:
    half = GroundPlane(true_calibration(), frame_size=(640, 360))
    u, v = project(4.0, 3.0)
    here = half.to_world(u / 2, v / 2)
    assert here is not None
    assert (here.east, here.north) == pytest.approx((4.0, 3.0), abs=1e-6)


def test_calibration_file_round_trip(tmp_path: Path) -> None:
    calib = true_calibration()
    path = tmp_path / "edge-01.calibration.yaml"
    calib.save(path)
    assert path.read_text().startswith("# Floor homography for edge-01")
    loaded = Calibration.load(path)
    np.testing.assert_allclose(loaded.matrix, calib.matrix)
    assert loaded.created_at == calib.created_at
