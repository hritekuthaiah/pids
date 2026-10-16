#!/usr/bin/env bash
# Export a YOLO detector to ONNX for the edge node.
#
# Runs Ultralytics in a throwaway tool environment (uvx), so PyTorch never enters
# the workspace: the edge node itself needs only ONNX Runtime. `end2end=True`
# keeps YOLO26's one-to-one head, whose output is already de-duplicated (no NMS).
#
#   apps/edge/scripts/export-model.sh [model] [imgsz]     e.g. yolo26s 640
set -euo pipefail

model="${1:-yolo26n}"
imgsz="${2:-640}"
ultralytics_version="8.4.178"

out_dir="$(cd "$(dirname "$0")/.." && pwd)/models"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$out_dir"

(
  cd "$work"
  uvx --python 3.12 --from "ultralytics==${ultralytics_version}" \
    --with onnx --with onnxslim --with onnxruntime \
    yolo export model="${model}.pt" format=onnx imgsz="${imgsz}" end2end=True
)
mv "$work/${model}.onnx" "$out_dir/${model}.onnx"
echo "wrote $out_dir/${model}.onnx"
shasum -a 256 "$out_dir/${model}.onnx"
