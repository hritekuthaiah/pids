"""Detector pre/post-processing (the parts that are ours, not the network's)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pids_core.contracts import EntityClass
from pids_edge.detector import (
    CLASS_ORDER,
    COCO80,
    Letterbox,
    YoloDetector,
    class_table,
    decode,
    iou_matrix,
    letterbox,
    nms,
    to_entities,
)

MODEL = Path(__file__).resolve().parents[1] / "models" / "yolo26n.onnx"


def test_letterbox_preserves_aspect_and_unmap_inverts_it() -> None:
    img = np.zeros((720, 1280, 3), np.uint8)
    tensor, lb = letterbox(img, 640)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert lb.scale == pytest.approx(0.5)
    assert (lb.pad_x, lb.pad_y) == (0.0, 140.0)
    original = np.array([[100, 200, 300, 600]], np.float32)
    in_net = original * lb.scale + np.array([lb.pad_x, lb.pad_y, lb.pad_x, lb.pad_y], np.float32)
    np.testing.assert_allclose(lb.unmap(in_net, 1280, 720), original, atol=1e-4)


def test_unmap_clips_to_the_frame() -> None:
    lb = Letterbox(scale=1.0, pad_x=0.0, pad_y=0.0)
    out = lb.unmap(np.array([[-10, -5, 2000, 900]], np.float32), 1280, 720)
    np.testing.assert_array_equal(out, [[0, 0, 1280, 720]])


def test_iou() -> None:
    a = np.array([[0, 0, 10, 10]], np.float32)
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]], np.float32)
    np.testing.assert_allclose(iou_matrix(a, b)[0], [1.0, 1 / 3, 0.0], atol=1e-6)
    assert iou_matrix(a, np.zeros((0, 4), np.float32)).shape == (1, 0)


def test_nms_suppresses_overlaps_and_keeps_best_first() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], np.float32)
    scores = np.array([0.6, 0.9, 0.7], np.float32)
    assert nms(boxes, scores, 0.5).tolist() == [1, 2]


def test_decode_end_to_end_layout() -> None:
    rows = np.array(
        [[[10, 20, 50, 120, 0.9, 0], [0, 0, 5, 5, 0.05, 2], [5, 5, 40, 40, 0.3, 16]]], np.float32
    )
    boxes, scores, cls = decode(rows, 0.1, 0.6)
    assert cls.tolist() == [0, 16]
    np.testing.assert_allclose(boxes[0], [10, 20, 50, 120])
    np.testing.assert_allclose(scores, [0.9, 0.3], atol=1e-6)


def test_decode_raw_layout_with_class_aware_nms() -> None:
    n = 5
    raw = np.zeros((1, 84, n), np.float32)
    # cx cy w h — two overlapping "person" candidates, one overlapping "dog", one weak, one car
    raw[0, :4, 0] = [50, 50, 20, 40]
    raw[0, :4, 1] = [51, 51, 20, 40]
    raw[0, :4, 2] = [50, 50, 20, 40]
    raw[0, :4, 3] = [200, 200, 10, 10]
    raw[0, :4, 4] = [300, 300, 40, 20]
    raw[0, 4 + 0, 0] = 0.8
    raw[0, 4 + 0, 1] = 0.7
    raw[0, 4 + 16, 2] = 0.6
    raw[0, 4 + 0, 3] = 0.05
    raw[0, 4 + 2, 4] = 0.5
    boxes, _, cls = decode(raw, 0.1, 0.6, num_classes=80)
    assert sorted(cls.tolist()) == [0, 2, 16]  # duplicate person suppressed, dog kept
    person = boxes[cls == 0][0]
    np.testing.assert_allclose(person, [40, 30, 60, 70])


def test_class_table_maps_by_name_and_ignores_the_rest() -> None:
    table = class_table(dict(enumerate(COCO80)))
    assert CLASS_ORDER[table[0]] is EntityClass.PERSON
    assert CLASS_ORDER[table[2]] is EntityClass.VEHICLE
    assert CLASS_ORDER[table[16]] is EntityClass.ANIMAL
    assert table[1] == -1  # bicycle: deliberately ignored
    assert table[63] == -1  # laptop
    custom = class_table({0: "dog", 1: "Person", 2: "forklift"})
    assert [CLASS_ORDER[i].value if i >= 0 else None for i in custom] == ["animal", "person", None]


def test_to_entities_drops_unmapped_and_out_of_range_classes() -> None:
    table = class_table(dict(enumerate(COCO80)))
    boxes = np.zeros((4, 4), np.float32)
    out = to_entities(
        boxes, np.array([0.9, 0.8, 0.7, 0.6], np.float32), np.array([0, 63, 7, 999]), table
    )
    assert [CLASS_ORDER[c].value for c in out.classes] == ["person", "vehicle"]


@pytest.mark.skipif(not MODEL.exists(), reason="model not exported (make edge-model)")
def test_real_model_runs_on_cpu_and_sees_nothing_in_an_empty_room() -> None:
    det = YoloDetector(MODEL, score_threshold=0.25)
    out = det(np.full((720, 1280, 3), 128, np.uint8))
    assert len(out) == 0
    assert det.last_inference_ms > 0
    assert det.names[0] == "person"
