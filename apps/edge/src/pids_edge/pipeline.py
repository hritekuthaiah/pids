"""The edge node: frames in, ``TrackBatch`` telemetry out.

``EdgeNode.process`` is the whole perception chain for one frame and has no I/O, so
it is tested end-to-end with synthetic detections. ``run`` wraps it with the camera,
MQTT, health reporting and the live preview.
"""

from __future__ import annotations

import itertools
import logging
import math
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import cv2
import numpy as np
from numpy.typing import NDArray

from pids_core.contracts import (
    EntityClass,
    GeoPoint,
    NodeHealth,
    NodeStatus,
    TrackBatch,
    VisionTrack,
    ZoneKind,
)
from pids_core.geo import Enu, heading_deg
from pids_core.site import NodeConfig, Site
from pids_edge.camera import Frame, FrameSource
from pids_edge.config import EdgeConfig
from pids_edge.detector import Detector
from pids_edge.ground import FloorFix, GroundPlane
from pids_edge.preview import PreviewServer
from pids_edge.publish import MqttPublisher
from pids_edge.thermal import ThermalArray, relative_bearing, warm_at
from pids_edge.tracker import ByteTracker, Track

log = logging.getLogger("pids_edge")


@dataclass(frozen=True, slots=True)
class Observed:
    """A published track with what was needed to draw it."""

    track: Track
    fix: FloorFix
    wire_id: str


@dataclass
class Rates:
    """Exponentially-smoothed throughput figures for health reports."""

    fps: float = 0.0
    inference_ms: float = 0.0
    _last: float | None = field(default=None, repr=False)

    def tick(self, t: float, inference_ms: float, alpha: float = 0.1) -> None:
        if self._last is not None and t > self._last:
            inst = 1.0 / (t - self._last)
            self.fps = inst if self.fps == 0 else (1 - alpha) * self.fps + alpha * inst
        self.inference_ms = (
            inference_ms
            if self.inference_ms == 0
            else (1 - alpha) * self.inference_ms + alpha * inference_ms
        )
        self._last = t


class EdgeNode:
    def __init__(
        self,
        config: EdgeConfig,
        site: Site,
        detector: Detector,
        ground: GroundPlane,
        *,
        boot: str | None = None,
        thermal: ThermalArray | None = None,
    ) -> None:
        nodes = {n.id: n for n in site.config.nodes}
        if config.node_id not in nodes:
            raise ValueError(f"node {config.node_id!r} is not declared in site {site.id!r}")
        self.config = config
        self.site = site
        self.node: NodeConfig = nodes[config.node_id]
        self.detector = detector
        self.ground = ground
        self.tracker = ByteTracker(config.tracker)
        # Tracker ids restart at 1 on every boot; the nonce keeps them unique.
        self.boot = boot or f"{int(time.time()) % 100_000:05d}"
        self._here = Enu(*self.node.position)
        self._max_range = self.node.range_m * config.ground.max_range_factor
        self.thermal = thermal

    def _heat(self, heat: NDArray[np.float32] | None, at: Enu) -> bool | None:
        """Heat confirmation at a floor position; None without thermal coverage there."""
        if heat is None or self.thermal is None:
            return None
        bearing = heading_deg(at.east - self._here.east, at.north - self._here.north)
        return warm_at(
            heat,
            relative_bearing(self.node.heading_deg, bearing),
            self.thermal.fov_deg,
            delta_c=self.config.sensors.thermal.delta_c,
        )

    def process(self, frame: Frame) -> tuple[TrackBatch, list[Observed]]:
        detections = self.detector(frame.image)
        tracks = self.tracker.update(detections, frame.monotonic)
        heat = self.thermal.frame() if self.thermal is not None else None
        observed: list[Observed] = []
        wire: list[VisionTrack] = []
        for tr in tracks:
            fix = self.ground.locate(tr.box)
            if fix is None or fix.position.distance_to(self._here) > self._max_range:
                continue  # above the horizon or implausibly far: a projection artefact
            lat, lon = self.site.frame.to_wgs84(fix.position)
            wire_id = f"{self.boot}-{tr.track_id}"
            wire.append(
                VisionTrack(
                    track_id=wire_id,
                    entity_class=tr.entity_class,
                    class_confidence=round(tr.class_confidence, 3),
                    position=GeoPoint(lat=lat, lon=lon),
                    position_sigma_m=round(fix.sigma_m, 3),
                    hits=tr.hits,
                    thermal_confirmed=self._heat(heat, fix.position),
                )
            )
            observed.append(Observed(tr, fix, wire_id))
        batch = TrackBatch(
            site_id=self.site.id,
            node_id=self.node.id,
            captured_at=frame.captured_at,
            tracks=wire,
            trace={"captured": frame.captured_at, "perceived": datetime.now(UTC)},
        )
        return batch, observed


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

_BGR = {
    EntityClass.PERSON: (80, 220, 255),
    EntityClass.VEHICLE: (255, 180, 60),
    EntityClass.ANIMAL: (120, 220, 120),
    EntityClass.UNKNOWN: (200, 200, 200),
}
_ZONE_BGR = {
    ZoneKind.WARNING: (31, 138, 255),
    ZoneKind.CRITICAL: (59, 59, 255),
    ZoneKind.CONTAINMENT: (255, 160, 80),
}


def _zone_lines(site: Site, ground: GroundPlane) -> list[tuple[ZoneKind, list[NDArray[np.int32]]]]:
    """Each zone outline as visible image polylines (edges sampled; horizon-clipped)."""
    out: list[tuple[ZoneKind, list[NDArray[np.int32]]]] = []
    for z in site.config.zones:
        ring = [*z.polygon, z.polygon[0]]
        runs: list[NDArray[np.int32]] = []
        current: list[tuple[int, int]] = []
        for (e0, n0), (e1, n1) in itertools.pairwise(ring):
            steps = max(2, math.ceil(math.hypot(e1 - e0, n1 - n0) / 0.25))
            for k in range(steps):
                f = k / steps
                px = ground.to_image(e0 + (e1 - e0) * f, n0 + (n1 - n0) * f)
                if px is None or not (-5000 < px[0] < 5000 and -5000 < px[1] < 5000):
                    if len(current) > 1:
                        runs.append(np.array(current, np.int32))
                    current = []
                    continue
                current.append((round(px[0]), round(px[1])))
        if len(current) > 1:
            runs.append(np.array(current, np.int32))
        out.append((z.kind, runs))
    return out


class Annotator:
    def __init__(self, site: Site, ground: GroundPlane, node_id: str) -> None:
        self._zones = _zone_lines(site, ground)
        self._node = node_id

    def draw(
        self, image: NDArray[np.uint8], observed: list[Observed], rates: Rates
    ) -> NDArray[np.uint8]:
        img = image.copy()
        for kind, runs in self._zones:
            cv2.polylines(
                img, runs, isClosed=False, color=_ZONE_BGR[kind], thickness=2, lineType=cv2.LINE_AA
            )
        for ob in observed:
            x1, y1, x2, y2 = (round(float(v)) for v in ob.track.box)
            colour = _BGR[ob.track.entity_class]
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2, cv2.LINE_AA)
            foot = ((x1 + x2) // 2, y2)
            cv2.circle(img, foot, 5, colour, -1, cv2.LINE_AA)
            p = ob.fix.position
            label = (
                f"#{ob.track.track_id} {ob.track.entity_class.value} {ob.track.class_confidence:.2f}"
                f"  ({p.east:.1f}, {p.north:.1f}) m  ±{ob.fix.sigma_m:.1f}"
            )
            _label(img, label, (x1, max(18, y1 - 6)), colour)
        hud = f"{self._node}  {rates.fps:4.1f} fps  infer {rates.inference_ms:4.1f} ms  tracks {len(observed)}"
        _label(img, hud, (10, 26), (230, 230, 230))
        _label(img, "LIVE  not recorded", (10, img.shape[0] - 12), (90, 90, 255))
        return img


def _label(
    img: NDArray[np.uint8], text: str, org: tuple[int, int], colour: tuple[int, int, int]
) -> None:
    """Text on a dark plate, kept inside the frame."""
    font, scale = cv2.FONT_HERSHEY_SIMPLEX, 0.55
    (w, h), base = cv2.getTextSize(text, font, scale, 1)
    x = min(max(3, org[0]), max(3, img.shape[1] - w - 4))
    y = min(max(h + 5, org[1]), img.shape[0] - base - 1)
    cv2.rectangle(img, (x - 3, y - h - 5), (x + w + 3, y + base), (16, 16, 16), -1)
    cv2.putText(img, text, (x, y), font, scale, colour, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Runtime loop
# ---------------------------------------------------------------------------


def run(
    node: EdgeNode,
    source: FrameSource,
    publisher: MqttPublisher | None,
    preview: PreviewServer | None,
    *,
    model_name: str,
    stop: threading.Event | None = None,
) -> None:
    cfg = node.config.publish
    stop = stop or threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    tracks_topic = f"pids/{node.site.id}/{node.node.id}/tracks"
    health_topic = f"pids/{node.site.id}/{node.node.id}/health"
    annotator = Annotator(node.site, node.ground, node.node.id) if preview else None
    rates = Rates()
    started = time.monotonic()
    last_publish = last_health = -math.inf
    current_tracks = 0

    def health(status: NodeStatus) -> bytes:
        return (
            NodeHealth(
                site_id=node.site.id,
                node_id=node.node.id,
                at=datetime.now(UTC),
                status=status,
                fps=round(rates.fps, 2),
                inference_ms=round(rates.inference_ms, 2),
                tracks=current_tracks,
                dropped_frames=getattr(source, "dropped", None),
                uptime_s=round(time.monotonic() - started, 1),
                model=model_name,
                calibration_rms_m=node.ground.calibration.rms_error_m,
            )
            .model_dump_json()
            .encode()
        )

    log.info("edge node %s running (boot %s)", node.node.id, node.boot)
    try:
        while not stop.is_set():
            frame = source.read()
            if frame is None:
                if not hasattr(source, "dropped"):  # a file source ended
                    break
                log.warning("no frame from camera")
                continue
            batch, observed = node.process(frame)
            current_tracks = len(observed)
            rates.tick(frame.monotonic, float(getattr(node.detector, "last_inference_ms", 0.0)))
            now = time.monotonic()
            if publisher and now - last_publish >= 1.0 / cfg.rate_hz:
                publisher.publish(tracks_topic, batch.model_dump_json().encode())
                last_publish = now
            if publisher and now - last_health >= cfg.health_period_s:
                publisher.publish(health_topic, health(NodeStatus.ONLINE), retain=True)
                last_health = now
            if preview and annotator:
                preview.status = {
                    "node_id": node.node.id,
                    "fps": round(rates.fps, 1),
                    "inference_ms": round(rates.inference_ms, 1),
                    "tracks": current_tracks,
                    "mqtt": bool(publisher and publisher.connected),
                }
                if preview.watched or frame.index % 15 == 0:
                    preview.submit(annotator.draw(frame.image, observed, rates))
    finally:
        log.info("edge node stopping")
        if publisher:
            publisher.stop(final=(health_topic, health(NodeStatus.OFFLINE)))
        source.close()
        if preview:
            preview.stop()
