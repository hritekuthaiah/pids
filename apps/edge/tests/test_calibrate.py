"""Calibration from printed ArUco floor markers, rendered through a known camera."""

from __future__ import annotations

from datetime import timedelta

import cv2
import numpy as np
import pytest

from edge_helpers import CAMERA, SIZE, T0, project
from pids_edge.calibrate import (
    ARUCO_DICT,
    FloorMark,
    FloorMarks,
    _diagonal_intersection,
    from_markers,
    marker_centres,
    pose_calibration,
)
from pids_edge.camera import Frame

PX_PER_M = 200  # floor texture resolution
MARKS = FloorMarks(
    points=[
        FloorMark(name="A", world=(2.5, 1.2), marker=0),
        FloorMark(name="B", world=(4.0, 1.0), marker=1),
        FloorMark(name="C", world=(6.0, 1.5), marker=2),
        FloorMark(name="D", world=(5.0, 3.5), marker=3),
        FloorMark(name="E", world=(3.0, 3.5), marker=4),
        FloorMark(name="F", world=(2.0, 2.5), marker=5),
    ]
)


def _floor_photo(marker_m: float = 0.4) -> np.ndarray:
    """What the camera sees: a grey floor with the markers lying on it."""
    w, h = int(8 * PX_PER_M), int(6 * PX_PER_M)
    floor = np.full((h, w), 170, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    side = int(marker_m * PX_PER_M)
    for m in MARKS.points:
        assert m.marker is not None
        tile = cv2.aruco.generateImageMarker(dictionary, m.marker, side)
        tile = cv2.copyMakeBorder(
            tile, side // 4, side // 4, side // 4, side // 4, cv2.BORDER_CONSTANT, value=255
        )
        cx, cy = int(m.world[0] * PX_PER_M), int((6 - m.world[1]) * PX_PER_M)
        half = tile.shape[0] // 2
        floor[cy - half : cy - half + tile.shape[0], cx - half : cx - half + tile.shape[1]] = tile
    # floor texture pixel (x, y) -> world (x/s, 6 - y/s) -> image via the camera's floor columns
    tex_to_world = np.array([[1 / PX_PER_M, 0, 0], [0, -1 / PX_PER_M, 6], [0, 0, 1]])
    world_to_image = CAMERA[:, [0, 1, 3]]
    warped = cv2.warpPerspective(floor, world_to_image @ tex_to_world, SIZE, borderValue=60)
    return cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR)


def test_diagonal_intersection_is_the_true_centre_under_perspective() -> None:
    square = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], np.float64)
    assert _diagonal_intersection(square) == pytest.approx((5, 5))
    quad = np.array([project(e, n) for e, n in [(2, 2), (2.5, 2), (2.5, 1.5), (2, 1.5)]])
    assert _diagonal_intersection(quad) == pytest.approx(project(2.25, 1.75), abs=1e-6)


def test_markers_are_found_where_they_lie() -> None:
    found = marker_centres(_floor_photo())
    assert set(found) == {0, 1, 2, 3, 4, 5}
    for m in MARKS.points:
        assert m.marker is not None
        assert np.hypot(*np.subtract(found[m.marker], project(*m.world))) < 2.5


def test_marker_calibration_is_centimetre_accurate() -> None:
    img = _floor_photo()
    frames = [Frame(img, i, T0 + timedelta(seconds=i), float(i)) for i in range(5)]
    calib = from_markers("edge-01", frames, MARKS)
    assert calib.method == "aruco"
    assert len(calib.points) == 6
    assert calib.rms_error_m < 0.03


def test_too_few_markers_is_an_error_not_a_bad_calibration() -> None:
    blank = np.full((SIZE[1], SIZE[0], 3), 120, np.uint8)
    with pytest.raises(RuntimeError, match="need 4"):
        from_markers("edge-01", [Frame(blank, 0, T0, 0.0)], MARKS)


def test_pose_calibration_states_its_uncertainty() -> None:
    calib = pose_calibration(
        "edge-01",
        SIZE,
        position=(0.3, 5.7),
        heading_deg=125,
        height_m=2.5,
        pitch_deg=28,
        hfov_deg=70,
    )
    assert calib.method == "pose"
    assert 0.1 < calib.rms_error_m < 1.0
