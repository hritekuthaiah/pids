"""ByteTrack behaviour and tracking quality on synthetic scenes."""

from __future__ import annotations

import numpy as np
import pytest

from edge_helpers import Walker, dets, random_scene, scene_detections
from pids_core.contracts import EntityClass
from pids_edge.config import TrackerConfig
from pids_edge.detector import Detections
from pids_edge.mot import MotCounter
from pids_edge.tracker import ByteTracker

DT = 1 / 15  # inference-bound edge rate


def _run(
    walkers: list[Walker], frames: int, seed: int = 0, clutter: float = 0.0
) -> tuple[MotCounter, list[set[int]]]:
    rng = np.random.default_rng(seed)
    tracker = ByteTracker()
    mot = MotCounter()
    for k in range(frames):
        d, gt_ids, gt_boxes = scene_detections(walkers, k, rng, clutter=clutter)
        tracks = tracker.update(d, k * DT)
        boxes = np.stack([t.box for t in tracks]) if tracks else np.zeros((0, 4), np.float32)
        mot.frame(gt_ids, gt_boxes, [t.track_id for t in tracks], boxes)
    return mot, [mot.ids_by_object.get(w.gid, set()) for w in walkers]


def test_one_walker_one_id() -> None:
    mot, ids = _run([Walker(0, 200, 400, 5, 0.5, 80, 200)], 120)
    assert len(ids[0]) == 1
    assert mot.id_switches == 0
    assert mot.misses <= 1  # only the very first frame can precede confirmation


def test_first_frame_tracks_confirm_immediately_later_ones_need_two_hits() -> None:
    tracker = ByteTracker()
    box = np.array([100, 100, 180, 300], np.float32)
    assert len(tracker.update(dets([box], [0.9]), 0.0)) == 1
    other = np.array([600, 100, 680, 300], np.float32)
    shown = tracker.update(dets([box + 3, other], [0.9, 0.9]), DT)
    assert len(shown) == 1  # the newcomer is tentative
    shown = tracker.update(dets([box + 6, other + 3], [0.9, 0.9]), 2 * DT)
    assert len(shown) == 2


def test_single_frame_ghost_is_never_reported() -> None:
    tracker = ByteTracker()
    tracker.update(Detections.empty(), 0.0)
    ghost = np.array([400, 200, 460, 330], np.float32)
    assert tracker.update(dets([ghost], [0.95]), DT) == []
    for k in range(2, 10):
        assert tracker.update(Detections.empty(), k * DT) == []


def test_low_score_detections_carry_a_track_through_partial_occlusion() -> None:
    # ByteTrack's point: a half-hidden person scoring 0.2-0.45 keeps their ID and stays visible.
    wk = Walker(0, 200, 400, 5, 0, 80, 200, occluded=[(20, 40, "low")])
    rng = np.random.default_rng(1)
    tracker = ByteTracker()
    reported_during_occlusion = 0
    ids: set[int] = set()
    for k in range(60):
        d, *_ = scene_detections([wk], k, rng)
        tracks = tracker.update(d, k * DT)
        ids |= {t.track_id for t in tracks}
        if 20 <= k < 40 and tracks:
            reported_during_occlusion += 1
    assert ids == {1}
    assert reported_during_occlusion == 20


def test_full_occlusion_shorter_than_buffer_keeps_the_id() -> None:
    gap = int(1.0 / DT)  # 1 s, inside the 1.5 s buffer
    mot, ids = _run([Walker(0, 200, 400, 5, 0, 80, 200, occluded=[(20, 20 + gap, "gone")])], 80)
    assert len(ids[0]) == 1
    assert mot.id_switches == 0


def test_occlusion_longer_than_buffer_starts_a_new_track() -> None:
    gap = int(2.5 / DT)
    _, ids = _run([Walker(0, 200, 400, 2, 0, 80, 200, occluded=[(20, 20 + gap, "gone")])], 80)
    assert len(ids[0]) == 2


def test_crossing_people_do_not_swap_ids() -> None:
    a = Walker(0, 150, 420, 7, 0, 90, 230)  # nearer: larger, lower in frame
    b = Walker(1, 1100, 380, -7, 0, 70, 180)
    mot, ids = _run([a, b], 150)
    assert mot.id_switches == 0
    assert len(ids[0]) == 1
    assert len(ids[1]) == 1


def test_class_is_a_vote_not_the_last_frame() -> None:
    tracker = ByteTracker()
    box = np.array([100, 100, 180, 300], np.float32)
    for k in range(30):
        cls = 2 if k % 10 == 9 else 0  # occasional "animal" flicker on a person
        tracks = tracker.update(dets([box + k], [0.85], [cls]), k * DT)
    assert tracks[0].entity_class is EntityClass.PERSON
    assert 0.0 < tracks[0].class_confidence <= 1.0


def test_lost_buffer_is_in_seconds_not_frames() -> None:
    tracker = ByteTracker(TrackerConfig(lost_buffer_s=0.5))
    box = np.array([100, 100, 180, 300], np.float32)
    tracker.update(dets([box], [0.9]), 0.0)
    tracker.update(Detections.empty(), 0.4)
    assert tracker.update(dets([box], [0.9]), 0.45)[0].track_id == 1
    tracker.update(Detections.empty(), 0.6)
    tracker.update(Detections.empty(), 1.2)
    tracker.update(dets([box], [0.9]), 1.25)
    assert [t.track_id for t in tracker.update(dets([box], [0.9]), 1.3)] == [2]


@pytest.mark.parametrize("seed", range(12))
def test_random_crowds_track_cleanly(seed: int) -> None:
    rng = np.random.default_rng(1000 + seed)
    walkers = random_scene(rng, int(rng.integers(2, 6)))
    mot, _ = _run(walkers, 150, seed=seed, clutter=0.3)
    assert mot.mota > 0.85
    assert mot.id_switches <= 2
