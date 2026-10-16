#!/usr/bin/env bash
# Detector accuracy (COCO val2017, per PIDS class) and edge benchmarks
# (PyTorch FP32 vs ONNX FP32 vs ONNX INT8), in a throwaway Ultralytics environment.
# First run downloads COCO val2017 (~1 GB) into data/datasets/ (git-ignored).
set -euo pipefail

ultralytics_version="8.4.178"
root="$(cd "$(dirname "$0")/../../.." && pwd)"

uvx --python 3.12 --from "ultralytics==${ultralytics_version}" \
  --with onnx --with onnxslim --with onnxruntime \
  python "$root/apps/edge/scripts/evaluate_detector.py" \
  --models "$root/apps/edge/models" \
  --datasets "$root/data/datasets" \
  --out "$root/docs/evaluation" "$@"
