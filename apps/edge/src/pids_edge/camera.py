"""Frame sources.

A live camera is read on its own thread and only the **newest** frame is kept: if
inference is slower than the sensor, stale frames are dropped instead of queueing,
so latency stays one frame deep instead of growing without bound (NFR-01). A video
file is read in order (every frame matters for replay and benchmarks).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from pids_edge.config import CameraConfig

log = logging.getLogger("pids_edge.camera")


@dataclass(frozen=True, slots=True)
class Frame:
    image: NDArray[np.uint8]
    index: int
    captured_at: datetime  # wall clock, for the wire
    monotonic: float  # for intervals

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h


class FrameSource(Protocol):
    def read(self, timeout_s: float = 2.0) -> Frame | None:
        """The next frame to process, or None if none arrived in time / the source ended."""

    def close(self) -> None:
        """Release the device."""


def _open(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int) and sys.platform == "darwin":
        return cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(source)


class LiveCamera:
    """A USB/built-in camera or network stream, read continuously on a thread."""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self._cap = self._connect()
        self._lock = threading.Condition()
        self._latest: Frame | None = None
        self._taken = -1
        self._count = 0
        self.dropped = 0
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def _connect(self) -> cv2.VideoCapture:
        cap = _open(self.config.source)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        cap.set(cv2.CAP_PROP_FPS, self.config.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise RuntimeError(
                f"camera {self.config.source!r} did not open — check the index "
                "(`pids-edge cameras`) and camera permission for this terminal"
            )
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info("camera %r open at %dx%d", self.config.source, w, h)
        return cap

    def _loop(self) -> None:
        failures = 0
        while self._running:
            ok, image = self._cap.read()
            if not ok:
                failures += 1
                if failures >= 30:  # unplugged or crashed: reopen with a pause
                    log.warning("camera read failing; reopening")
                    self._cap.release()
                    time.sleep(1.0)
                    try:
                        self._cap = self._connect()
                    except RuntimeError as exc:
                        log.error("%s", exc)
                    failures = 0
                time.sleep(0.01)
                continue
            failures = 0
            frame = Frame(
                np.asarray(image, dtype=np.uint8), self._count, datetime.now(UTC), time.monotonic()
            )
            self._count += 1
            with self._lock:
                if self._latest is not None and self._latest.index != self._taken:
                    self.dropped += 1
                self._latest = frame
                self._lock.notify_all()

    def read(self, timeout_s: float = 2.0) -> Frame | None:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while self._latest is None or self._latest.index == self._taken:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._running:
                    return None
                self._lock.wait(remaining)
            self._taken = self._latest.index
            return self._latest

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)
        self._cap.release()


class VideoFile:
    """Every frame of a recording, optionally paced at its native rate."""

    def __init__(self, path: Path, *, realtime: bool = True) -> None:
        self._cap = cv2.VideoCapture(str(path))
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open video {path}")
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._realtime = realtime
        self._index = 0
        self._t0 = time.monotonic()

    def read(self, timeout_s: float = 2.0) -> Frame | None:
        del timeout_s  # a file never blocks
        ok, image = self._cap.read()
        if not ok:
            return None
        if self._realtime:
            delay = self._t0 + self._index / self._fps - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        frame = Frame(
            np.asarray(image, dtype=np.uint8), self._index, datetime.now(UTC), time.monotonic()
        )
        self._index += 1
        return frame

    def close(self) -> None:
        self._cap.release()


def open_source(config: CameraConfig) -> FrameSource:
    src = config.source
    if isinstance(src, str) and Path(src).is_file():
        return VideoFile(Path(src))
    return LiveCamera(config)


def probe(max_index: int = 5) -> list[tuple[int, int, int]]:
    """Camera indices that open, with their default resolution."""
    found: list[tuple[int, int, int]] = []
    for i in range(max_index + 1):
        cap = _open(i)
        if cap.isOpened():
            ok, image = cap.read()
            if ok:
                found.append((i, image.shape[1], image.shape[0]))
        cap.release()
    return found
