"""Object detection with a YOLO model on ONNX Runtime (AIL-01, AIL-14).

Handles both export layouts Ultralytics produces:

* **end-to-end** (YOLO26, YOLOv10): ``(1, K, 6)`` rows of ``x1 y1 x2 y2 score class``,
  already de-duplicated by the network — no NMS needed;
* **raw** (YOLOv8/YOLO11): ``(1, 4 + C, N)`` centre-format boxes with per-class scores,
  which need confidence filtering and class-aware NMS here.

Model classes are mapped to PIDS entity classes **by name** from the model's own
metadata, so a fine-tuned model with a different class list maps correctly.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from pids_core.contracts import EntityClass

Image = NDArray[np.uint8]
F32 = NDArray[np.float32]

#: Order of ``Detections.classes`` codes.
CLASS_ORDER: tuple[EntityClass, ...] = (EntityClass.PERSON, EntityClass.VEHICLE, EntityClass.ANIMAL)

# Bicycles are deliberately unmapped: a rider is detected as a person anyway, and a
# parked bicycle tracked as a "vehicle inside the compound" is a pure nuisance alarm.
_NAME_TO_ENTITY: dict[str, EntityClass] = {
    "person": EntityClass.PERSON,
    **dict.fromkeys(("car", "motorcycle", "bus", "truck"), EntityClass.VEHICLE),
    **dict.fromkeys(
        ("bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"),
        EntityClass.ANIMAL,
    ),
}

# The 80 COCO class names, for models exported without metadata.
COCO80: tuple[str, ...] = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic_light",
    "fire_hydrant",
    "stop_sign",
    "parking_meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports_ball",
    "kite",
    "baseball_bat",
    "baseball_glove",
    "skateboard",
    "surfboard",
    "tennis_racket",
    "bottle",
    "wine_glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot_dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted_plant",
    "bed",
    "dining_table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell_phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy_bear",
    "hair_drier",
    "toothbrush",
)


@dataclass(frozen=True, slots=True)
class Detections:
    """Detections in original-image pixels. ``classes`` index into ``CLASS_ORDER``."""

    boxes: F32  # (N, 4) x1 y1 x2 y2
    scores: F32  # (N,)
    classes: NDArray[np.int64]  # (N,)

    def __len__(self) -> int:
        return int(self.scores.shape[0])

    @staticmethod
    def empty() -> Detections:
        return Detections(
            np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, np.int64)
        )

    def subset(self, mask: NDArray[np.bool_]) -> Detections:
        return Detections(self.boxes[mask], self.scores[mask], self.classes[mask])


class Detector(Protocol):
    def __call__(self, image: Image) -> Detections:
        """Detect people, vehicles and animals in one BGR frame."""


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Letterbox:
    """How a frame was resized and padded into the square network input."""

    scale: float
    pad_x: float
    pad_y: float

    def unmap(self, boxes: F32, width: int, height: int) -> F32:
        """Network-input pixels -> original-image pixels, clipped to the frame."""
        out = boxes.copy()
        out[:, [0, 2]] = (out[:, [0, 2]] - self.pad_x) / self.scale
        out[:, [1, 3]] = (out[:, [1, 3]] - self.pad_y) / self.scale
        out[:, [0, 2]] = out[:, [0, 2]].clip(0, width)
        out[:, [1, 3]] = out[:, [1, 3]].clip(0, height)
        return out


def letterbox(image: Image, size: int) -> tuple[F32, Letterbox]:
    """Resize preserving aspect ratio, pad with grey to ``size``², return NCHW RGB [0,1]."""
    h, w = image.shape[:2]
    scale = min(size / h, size / w)
    nw, nh = round(w * scale), round(h * scale)
    pad_x, pad_y = (size - nw) / 2, (size - nh) / 2
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top, left = round(pad_y - 0.1), round(pad_x - 0.1)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top : top + nh, left : left + nw] = resized
    tensor = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return np.ascontiguousarray(tensor), Letterbox(scale, float(left), float(top))


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def iou_matrix(a: F32, b: F32) -> F32:
    """Pairwise IoU of two sets of xyxy boxes, shape ``(len(a), len(b))``."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), np.float32)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.asarray(inter / np.maximum(union, 1e-9), dtype=np.float32)


def nms(boxes: F32, scores: F32, iou_threshold: float) -> NDArray[np.int64]:
    """Greedy non-maximum suppression; returns kept indices, best first."""
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        overlap = iou_matrix(boxes[i : i + 1], boxes[order[1:]])[0]
        order = order[1:][overlap <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def decode(
    output: NDArray[np.float32],
    score_threshold: float,
    iou_threshold: float,
    num_classes: int | None = None,
) -> tuple[F32, F32, NDArray[np.int64]]:
    """Network output -> ``(boxes_xyxy, scores, model_class_ids)`` in input pixels."""
    out = output[0] if output.ndim == 3 else output
    if out.shape[-1] == 6:  # end-to-end: x1 y1 x2 y2 score class
        keep = out[:, 4] >= score_threshold
        rows = out[keep]
        return (
            rows[:, :4].astype(np.float32),
            rows[:, 4].astype(np.float32),
            rows[:, 5].astype(np.int64),
        )
    channels_first = out.shape[0] == 4 + num_classes if num_classes else out.shape[0] < out.shape[1]
    if channels_first:  # (4 + C, N) -> (N, 4 + C)
        out = out.T
    class_scores = out[:, 4:]
    cls = class_scores.argmax(axis=1)
    score = class_scores[np.arange(len(cls)), cls]
    keep = score >= score_threshold
    cxcywh, score, cls = out[keep, :4], score[keep], cls[keep]
    boxes = np.empty_like(cxcywh)
    boxes[:, :2] = cxcywh[:, :2] - cxcywh[:, 2:] / 2
    boxes[:, 2:] = cxcywh[:, :2] + cxcywh[:, 2:] / 2
    # Class-aware NMS in one pass: shift each class into its own coordinate island.
    offset = cls[:, None].astype(np.float32) * 8192.0
    kept = nms((boxes + offset).astype(np.float32), score.astype(np.float32), iou_threshold)
    return (
        boxes[kept].astype(np.float32),
        score[kept].astype(np.float32),
        cls[kept].astype(np.int64),
    )


def class_table(names: dict[int, str]) -> NDArray[np.int64]:
    """Model class id -> index into ``CLASS_ORDER``, or -1 for classes PIDS ignores."""
    size = max(names, default=-1) + 1
    table = np.full(size, -1, dtype=np.int64)
    for idx, name in names.items():
        entity = _NAME_TO_ENTITY.get(name.strip().lower())
        if entity is not None:
            table[idx] = CLASS_ORDER.index(entity)
    return table


def to_entities(
    boxes: F32, scores: F32, model_classes: NDArray[np.int64], table: NDArray[np.int64]
) -> Detections:
    in_range = (model_classes >= 0) & (model_classes < len(table))
    mapped = np.full(len(model_classes), -1, dtype=np.int64)
    mapped[in_range] = table[model_classes[in_range]]
    keep = mapped >= 0
    return Detections(boxes[keep], scores[keep], mapped[keep])


# ---------------------------------------------------------------------------
# ONNX Runtime detector
# ---------------------------------------------------------------------------


def _model_names(meta: dict[str, str]) -> dict[int, str]:
    raw = meta.get("names")
    if raw:
        parsed = ast.literal_eval(raw)  # Ultralytics stores a dict literal; never eval()
        if isinstance(parsed, dict):
            return {int(k): str(v) for k, v in parsed.items()}
    return dict(enumerate(COCO80))


class YoloDetector:
    """A YOLO ONNX model on the CPU execution provider (the Pi-class target, ADR-0006)."""

    def __init__(
        self,
        model: Path,
        score_threshold: float = 0.1,
        iou_threshold: float = 0.6,
        threads: int = 0,
    ) -> None:
        import onnxruntime as ort

        if not model.exists():
            raise FileNotFoundError(f"{model} not found — run `make edge-model` first")
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            opts.intra_op_num_threads = threads
        self._session = ort.InferenceSession(
            str(model), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        inp = self._session.get_inputs()[0]
        self._input = str(inp.name)
        side = inp.shape[2]
        self.input_size = side if isinstance(side, int) else 640
        meta: dict[str, str] = dict(self._session.get_modelmeta().custom_metadata_map)
        self.names = _model_names(meta)
        self.table = class_table(self.names)
        self.score_threshold = score_threshold
        self.iou_threshold = iou_threshold
        self.last_inference_ms = 0.0

    def __call__(self, image: Image) -> Detections:
        h, w = image.shape[:2]
        tensor, lb = letterbox(image, self.input_size)
        t0 = time.perf_counter()
        output = self._session.run(None, {self._input: tensor})[0]
        self.last_inference_ms = (time.perf_counter() - t0) * 1000.0
        boxes, scores, cls = decode(
            np.asarray(output, dtype=np.float32),
            self.score_threshold,
            self.iou_threshold,
            len(self.names),
        )
        if len(scores) == 0:
            return Detections.empty()
        return to_entities(lb.unmap(boxes, w, h), scores, cls, self.table)
