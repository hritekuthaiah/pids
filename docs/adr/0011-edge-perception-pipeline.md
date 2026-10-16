# ADR-0011: Edge perception — YOLO26 (ONNX), ByteTrack, floor homography

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** AIL-01, AIL-02, AIL-14, NFR-01, NFR-04, NFR-07

## Context

The edge node must turn a camera into `TrackBatch` telemetry on Pi-class ARM64 CPUs
(ADR-0006): people, vehicles and animals, with IDs stable enough for behavioural
features, placed on the site in metres with an honest error estimate. The live demo
is a room with a camera high in a corner, so placement has to be accurate to tens of
centimetres and quick to redo if the camera is bumped.

## Decision

- **Detector: Ultralytics YOLO26n, exported end-to-end to ONNX, run on ONNX Runtime's
  CPU provider.** YOLO26's one-to-one head emits de-duplicated boxes, so no NMS on the
  edge (the decoder still supports raw YOLOv8/11 output with class-aware NMS). On the
  demo laptop's CPU it measures ~17 ms per 640² frame against ~24 ms for the NMS
  export of the same weights. COCO classes map to PIDS classes **by name** from the
  model's metadata, so a fine-tuned model maps correctly. Bicycles are deliberately
  unmapped (riders are detected as people; parked bicycles would be nuisance alarms).
  Export runs in a throwaway `uvx` environment: PyTorch never enters the workspace.
  Licence: Ultralytics is AGPL-3.0, compatible with this repository (ADR-0008).
- **Tracker: ByteTrack**, implemented here (≈200 lines, unit-tested) rather than
  imported, faithful to the reference except that the lost-track buffer is in
  seconds — the edge frame rate is inference-bound, not fixed. Low-score detections
  get a second association pass, which keeps partly occluded people on their ID.
  Classes are a per-track exponential vote, not the last frame's label.
- **Placement: a floor homography** from image pixels to site metres, applied to each
  box's foot point. Three ways to fit it: printed **ArUco markers** on surveyed floor
  points (found automatically; centre = diagonal intersection, exact under
  perspective), **clicked tape marks**, or a **pose estimate** from the tape-measured
  mounting. RANSAC rejects a bad mark when six or more are used. The fit's RMS error is
  stored with it and zones are drawn back on the camera image as a visual check.
- **Uncertainty is propagated:** foot-point pixel noise goes through the homography's
  Jacobian, plus the calibration RMS. Far people and people whose feet are cut off by
  the frame report a larger `position_sigma_m`, which the decision Kalman uses.
- **Privacy:** the annotated preview is MJPEG on loopback, encoded only while watched,
  never written to disk, without CORS headers and with a Host check against DNS
  rebinding (NFR-04).
- **Telemetry:** MQTT as the node's own user (ACL, ADR-0003), 5 Hz track batches,
  retained `NodeHealth` with an `offline` last will, and a bounded store-and-forward
  outbox that replays only messages young enough to still be meaningful.

## Alternatives considered

- *YOLO11n:* same toolchain, needs NMS, slower on CPU in our measurement.
- *Library trackers (supervision, BoxMOT):* heavier dependencies for one algorithm we
  need to explain and tune; ours is small enough to own and test.
- *Full camera calibration (intrinsics + extrinsics):* more steps for the operator;
  the floor is the only surface we project onto, and a homography captures it exactly.

## Consequences

The edge needs only ONNX Runtime, OpenCV and NumPy/SciPy. A synthetic camera in the
tests checks the chain to centimetres; on 200 held-out synthetic constant-velocity
scenes ByteTrack scores MOTA 0.999 with no ID switches — an upper bound, since real
footage adds non-linear motion and appearance confusion. Per-class detection accuracy
on real images and PyTorch/ONNX/INT8 benchmarks remain open work (#22, #26).
