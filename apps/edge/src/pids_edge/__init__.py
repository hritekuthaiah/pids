"""PIDS edge node: turns a camera into ``TrackBatch`` telemetry for the decision core.

    camera ─▶ YOLO (ONNX Runtime) ─▶ ByteTrack ─▶ ground plane (homography) ─▶ MQTT

Everything downstream of the camera is deterministic given the frames, so the
pipeline is tested end-to-end with synthetic detections projected through a known
camera model.
"""

__version__ = "0.1.0"
