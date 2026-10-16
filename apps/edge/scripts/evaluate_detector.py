"""Detector accuracy and edge benchmarks: PyTorch FP32 vs ONNX FP32 vs ONNX INT8 (#22, #26).

Runs inside the throwaway Ultralytics tool environment (``evaluate-detector.sh``), so
PyTorch never enters the workspace. Steps:

1. INT8: static post-training quantisation of the ONNX model (QDQ, per-channel weights)
   calibrated on 128 COCO val images — Conv/MatMul only, so the end-to-end head's
   TopK/Gather selection stays in float.
2. Accuracy: COCO val2017 (5000 images) through Ultralytics' validator for each model
   (only val is fetched: ~780 MB of images plus the ~46 MB YOLO-format label pack);
   per-class AP is folded into the PIDS classes (person / vehicle / animal) with the
   same name mapping the edge uses.
3. Latency: 200 timed single-image inferences at 640x640 on the CPU after warm-up —
   network only (pre/post-processing is identical across formats).

Writes ``docs/evaluation/detector.json`` and ``docs/evaluation/detector.md``.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

import numpy as np

PIDS_CLASSES = {
    "person": ["person"],
    "vehicle": ["car", "motorcycle", "bus", "truck"],
    "animal": [
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
    ],
}


LABELS_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco2017labels.zip"
IMAGES_URL = "http://images.cocodataset.org/zips/val2017.zip"


def _fetch(url: str, dest: Path) -> None:
    import urllib.request

    if dest.exists():
        return
    print(f"downloading {url}")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https/http dataset URLs
    tmp.rename(dest)


def prepare_val(datasets: Path) -> Path:
    """COCO val2017 only, in YOLO layout, plus a dataset YAML pointing at it."""
    import zipfile

    import yaml
    from ultralytics.utils.checks import check_yaml

    root = datasets / "coco-val"
    images, labels = root / "images" / "val2017", root / "labels" / "val2017"
    root.mkdir(parents=True, exist_ok=True)
    if len(list(labels.glob("*.txt"))) < 4900:
        _fetch(LABELS_URL, root / "labels.zip")
        with zipfile.ZipFile(root / "labels.zip") as z:
            for m in z.namelist():
                if m.startswith("coco/labels/val2017/") and m.endswith(".txt"):
                    labels.mkdir(parents=True, exist_ok=True)
                    (labels / Path(m).name).write_bytes(z.read(m))
    if len(list(images.glob("*.jpg"))) < 5000:
        _fetch(IMAGES_URL, root / "val2017.zip")
        with zipfile.ZipFile(root / "val2017.zip") as z:
            z.extractall(root / "images")
    names = yaml.safe_load(Path(check_yaml("coco.yaml")).read_text())["names"]
    cfg = root / "coco-val.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {"path": str(root), "train": "images/val2017", "val": "images/val2017", "names": names}
        )
    )
    return cfg


def quantize(fp32: Path, int8: Path, images: list[Path]) -> None:
    import cv2
    from onnxruntime.quantization import (
        CalibrationDataReader,
        QuantFormat,
        QuantType,
        quantize_static,
    )
    from onnxruntime.quantization.shape_inference import quant_pre_process

    def tensor(path: Path) -> np.ndarray:
        img = cv2.imread(str(path))
        h, w = img.shape[:2]
        s = min(640 / h, 640 / w)
        nw, nh = round(w * s), round(h * s)
        canvas = np.full((640, 640, 3), 114, np.uint8)
        top, left = (640 - nh) // 2, (640 - nw) // 2
        canvas[top : top + nh, left : left + nw] = cv2.resize(img, (nw, nh))
        return (canvas[:, :, ::-1].transpose(2, 0, 1)[None] / 255.0).astype(np.float32)

    class Reader(CalibrationDataReader):
        def __init__(self) -> None:
            self._it = iter(images)

        def get_next(self) -> dict[str, np.ndarray] | None:
            p = next(self._it, None)
            return None if p is None else {"images": tensor(p)}

    pre = int8.with_suffix(".pre.onnx")
    quant_pre_process(str(fp32), str(pre), skip_symbolic_shape=True)
    quantize_static(
        str(pre),
        str(int8),
        Reader(),
        quant_format=QuantFormat.QDQ,
        per_channel=True,
        weight_type=QuantType.QInt8,
        activation_type=QuantType.QUInt8,
        op_types_to_quantize=["Conv", "MatMul"],
    )
    pre.unlink(missing_ok=True)


def latency_ms(model: Path, runs: int = 200) -> list[float]:
    x = np.random.default_rng(0).random((1, 3, 640, 640), dtype=np.float32)
    if model.suffix == ".pt":
        import torch
        from ultralytics import YOLO

        net = YOLO(str(model)).model.eval().float()
        t = torch.from_numpy(x)
        with torch.inference_mode():
            for _ in range(20):
                net(t)
            out = []
            for _ in range(runs):
                t0 = time.perf_counter()
                net(t)
                out.append((time.perf_counter() - t0) * 1000)
        return out
    import onnxruntime as ort

    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    for _ in range(20):
        sess.run(None, {name: x})
    out = []
    for _ in range(runs):
        t0 = time.perf_counter()
        sess.run(None, {name: x})
        out.append((time.perf_counter() - t0) * 1000)
    return out


def accuracy(model: Path, data: str) -> dict[str, object]:
    import tempfile

    from ultralytics import YOLO

    m = YOLO(str(model), task="detect")
    r = m.val(
        project=tempfile.mkdtemp(prefix="pids-val-"),
        data=data,
        imgsz=640,
        batch=1 if model.suffix == ".onnx" else 16,
        device="cpu",
        plots=False,
        verbose=False,
    )
    names: dict[int, str] = r.names
    ap = {names[int(c)]: float(r.box.maps[int(c)]) for c in r.box.ap_class_index}
    ap50 = {names[int(c)]: float(v) for c, v in zip(r.box.ap_class_index, r.box.ap50, strict=True)}
    rec = {names[int(c)]: float(v) for c, v in zip(r.box.ap_class_index, r.box.r, strict=True)}
    per_pids = {}
    for pids, members in PIDS_CLASSES.items():
        present = [n for n in members if n in ap]
        per_pids[pids] = {
            "mAP50-95": statistics.fmean(ap[n] for n in present),
            "mAP50": statistics.fmean(ap50[n] for n in present),
            "recall": statistics.fmean(rec[n] for n in present),
            "coco_classes": present,
        }
    return {"mAP50-95": float(r.box.map), "mAP50": float(r.box.map50), "pids": per_pids}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--datasets", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="yolo26n")
    ap.add_argument("--latency-only", action="store_true", help="re-time models, keep accuracy")
    args = ap.parse_args()
    if args.latency_only:
        retime(args.out, args.models)
        return

    data = str(prepare_val(args.datasets.resolve()))
    val_images = sorted((args.datasets.resolve() / "coco-val" / "images" / "val2017").glob("*.jpg"))

    pt = args.models / f"{args.name}.pt"
    fp32 = args.models / f"{args.name}.onnx"
    int8 = args.models / f"{args.name}-int8.onnx"
    if not pt.exists():
        from ultralytics import YOLO

        YOLO(f"{args.name}.pt")  # downloads the official weights
        Path(f"{args.name}.pt").rename(pt)
    if not int8.exists():
        quantize(fp32, int8, val_images[:128])

    results = {}
    for label, path in (("PyTorch FP32", pt), ("ONNX FP32", fp32), ("ONNX INT8", int8)):
        lat = latency_ms(path)
        results[label] = {
            "file": path.name,
            "size_mb": round(path.stat().st_size / 1e6, 2),
            "latency_p50_ms": round(statistics.median(lat), 2),
            "latency_p95_ms": round(float(np.percentile(lat, 95)), 2),
            "fps": round(1000 / statistics.median(lat), 1),
            **accuracy(path, data),
        }
        print(label, json.dumps(results[label]))

    meta = {
        "machine": f"{platform.machine()} {platform.processor() or platform.platform()}",
        "eval_set": f"COCO val2017 ({len(val_images)} images); INT8 calibrated on the first 128",
        "imgsz": 640,
    }
    write(args.out, meta, results)


def write(out: Path, meta: dict[str, object], results: dict[str, dict[str, object]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "detector.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2) + "\n"
    )
    summary = (
        f"Generated by `make edge-eval`: {meta['eval_set']}, {meta['imgsz']}x{meta['imgsz']}, "
        f"CPU only ({meta['machine']}). Latency is the network alone, single image, after warm-up, "
        "measured on an otherwise idle machine."
    )
    header = (
        "| Model | Size (MB) | p50 latency (ms) | p95 (ms) | FPS | COCO mAP50-95 "
        "| person AP | vehicle AP | animal AP | person recall |"
    )
    lines = [
        "# Detector evaluation and edge benchmarks",
        "",
        summary,
        "",
        header,
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, r in results.items():
        pids: dict[str, dict[str, float]] = r["pids"]  # type: ignore[assignment]
        lines.append(
            f"| {label} | {r['size_mb']} | {r['latency_p50_ms']} | {r['latency_p95_ms']} | {r['fps']} | "
            f"{float(r['mAP50-95']):.3f} | {pids['person']['mAP50-95']:.3f} | {pids['vehicle']['mAP50-95']:.3f} | "  # type: ignore[arg-type]
            f"{pids['animal']['mAP50-95']:.3f} | {pids['person']['recall']:.3f} |"
        )
    note = (
        "PIDS class AP is the mean COCO AP50-95 of its member classes "
        "(vehicle: car, motorcycle, bus, truck; animal: ten COCO animal classes). "
        "Recall is Ultralytics' per-class recall at the F1-optimal confidence."
    )
    lines += ["", note]
    (out / "detector.md").write_text("\n".join(lines) + "\n")


def retime(out: Path, models: Path) -> None:
    """Re-measure latency only (accuracy is unaffected by machine load), keep the rest."""
    data = json.loads((out / "detector.json").read_text())
    for r in data["results"].values():
        lat = latency_ms(models / str(r["file"]))
        r["latency_p50_ms"] = round(statistics.median(lat), 2)
        r["latency_p95_ms"] = round(float(np.percentile(lat, 95)), 2)
        r["fps"] = round(1000 / statistics.median(lat), 1)
        print(r["file"], r["latency_p50_ms"], "ms")
    write(out, data["meta"], data["results"])


if __name__ == "__main__":
    main()
