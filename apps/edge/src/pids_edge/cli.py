"""``pids-edge`` — run and calibrate a camera edge node.

    pids-edge cameras                         list camera indices that open
    pids-edge run --config config/edge/edge-01.yaml
    pids-edge calibrate --config ... --marks config/edge/edge-01.marks.yaml [--mode click]
    pids-edge calibrate-pose --config ... --height 2.4 --pitch 30 --hfov 70
    pids-edge markers --out markers/ --ids 0-5
    pids-edge gps --probe                     identify a plugged-in GPS module
    pids-edge gps --config ...                stream GPS fixes to MQTT (no camera)
    pids-edge ble                             list PIDS badges heard over Bluetooth
    pids-edge camera-test <url>               check a phone camera stream

MQTT credentials come from the environment (``MQTT_HOST``, ``MQTT_PORT``,
``MQTT_EDGE_USER``, ``MQTT_EDGE_PASSWORD``); ``make edge`` loads them from ``.env``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pids_core.contracts import NodeHealth, NodeStatus
from pids_core.site import Site
from pids_edge.config import EdgeConfig

if TYPE_CHECKING:
    from datetime import datetime

    from pids_edge.ble import BadgeScanner
    from pids_edge.gps import GpsReader
    from pids_edge.nmea import Fix
    from pids_edge.publish import MqttPublisher

log = logging.getLogger("pids_edge")

_DEFAULT_CONFIG = Path("config/edge/edge-01.yaml")


def cmd_cameras(_: argparse.Namespace) -> int:
    from pids_edge.camera import probe

    found = probe()
    if not found:
        log.error("no camera opened — check it is plugged in and this terminal may use the camera")
        return 1
    for index, w, h in found:
        log.info("camera %d: %dx%d", index, w, h)
    return 0


class _NoCredentialsError(Exception):
    pass


def _publisher(cfg: EdgeConfig, site: Site) -> MqttPublisher:
    """This node's MQTT connection (username = node id, per the broker ACL)."""
    from datetime import UTC, datetime

    from pids_edge.publish import MqttPublisher, Outbox

    user = os.environ.get("MQTT_EDGE_USER", cfg.node_id)
    if user != cfg.node_id:
        log.warning(
            "MQTT_EDGE_USER=%s but node is %s: the broker ACL will refuse it", user, cfg.node_id
        )
    password = os.environ.get("MQTT_EDGE_PASSWORD")
    if not password:
        raise _NoCredentialsError("MQTT_EDGE_PASSWORD is not set (use `make edge`, or --offline)")
    will = NodeHealth(
        site_id=site.id, node_id=cfg.node_id, at=datetime.now(UTC), status=NodeStatus.OFFLINE
    )
    ca = os.environ.get("MQTT_CA_FILE")  # set -> TLS to the broker on 8883, verified
    publisher = MqttPublisher(
        host=os.environ.get("MQTT_HOST", "localhost"),
        port=int(os.environ.get("MQTT_PORT", "8883" if ca else "1883")),
        username=user,
        password=password,
        client_id=f"pids-edge-{cfg.node_id}",
        outbox=Outbox(cfg.publish.buffer_limit, cfg.publish.replay_window_s),
        will=(f"pids/{site.id}/{cfg.node_id}/health", will.model_dump_json().encode()),
        ca_file=Path(ca) if ca else None,
    )
    publisher.start()
    return publisher


def _start_gps(cfg: EdgeConfig, site: Site, publisher: MqttPublisher | None) -> GpsReader | None:
    from pids_edge.gps import GpsReader, to_contract

    g = cfg.sensors.gps
    if g.driver == "none" or g.tag_id is None:
        return None
    tag_id = g.tag_id
    topic = f"pids/{site.id}/{cfg.node_id}/gps"

    def on_fix(fix: Fix) -> None:
        msg = to_contract(site.id, tag_id, fix)
        log.info(
            "GPS %s: %.6f, %.6f  ±%.1f m  %s sats",
            tag_id, fix.lat, fix.lon, fix.accuracy_m, fix.satellites if fix.satellites is not None else "?",
        )  # fmt: skip
        if publisher:
            publisher.publish(topic, msg.model_dump_json().encode())

    reader = GpsReader(on_fix, port=g.port, baud=g.baud)
    reader.start()
    return reader


def _start_ble(cfg: EdgeConfig, site: Site, publisher: MqttPublisher | None) -> BadgeScanner | None:
    from pids_core.badges import BadgeResolver
    from pids_core.contracts import TagRead
    from pids_edge.ble import BadgeAggregator, BadgeScanner, site_key_from_env

    b = cfg.sensors.ble
    if b.driver == "none" or b.reader_id is None:
        return None
    reader = site.readers.get(b.reader_id)
    if reader is None or reader.kind != "ble":
        raise ValueError(f"{b.reader_id!r} is not a `kind: ble` reader in {cfg.site}")
    reader_id = b.reader_id
    topic = f"pids/{site.id}/{cfg.node_id}/sensors"

    def on_read(tag: str, rssi: float, at: datetime) -> None:
        log.debug("badge %s %.0f dBm", tag, rssi)
        if publisher:
            read = TagRead(
                site_id=site.id, reader_id=reader_id, tag_id=tag, at=at, rssi_dbm=round(rssi, 1),
                trace={"captured": at},
            )  # fmt: skip
            publisher.publish(topic, read.model_dump_json().encode())

    resolver = BadgeResolver(site_key_from_env(), site.tags, allow_static=b.allow_static)
    scanner = BadgeScanner(BadgeAggregator(resolver, on_read))
    scanner.start()
    return scanner


def cmd_camera_test(args: argparse.Namespace) -> int:
    """Open a phone or IP camera stream and report what the edge node would get."""
    import statistics
    import time

    from pids_edge.camera import LiveCamera, is_network
    from pids_edge.config import CameraConfig

    url = args.url
    if not is_network(url):
        log.error("expected a stream URL (http://, https://, rtsp://), got %r", url)
        return 2
    log.info("opening %s", url)
    opened = time.monotonic()
    try:
        cam = LiveCamera(CameraConfig(source=url))
    except RuntimeError as exc:
        log.error("%s", exc)
        log.error(
            "checklist: phone and laptop on the same wifi; the streaming screen open; "
            "the URL copied exactly (most apps show it); no VPN on either device"
        )
        return 1
    try:
        first = cam.read(timeout_s=15.0)
        if first is None:
            log.error("connected but no frame arrived within 15 s")
            return 1
        log.info("first frame after %.1f s: %dx%d", time.monotonic() - opened, *first.size)
        times = []
        last = first.monotonic
        for _ in range(args.frames):
            frame = cam.read(timeout_s=10.0)
            if frame is None:
                break
            times.append(frame.monotonic - last)
            last = frame.monotonic
        if times:
            fps = 1.0 / statistics.median(times)
            log.info("%d frames, median %.1f fps, %d dropped", len(times), fps, cam.dropped)
            if fps < 8:
                log.warning(
                    "under 8 fps: lower the phone's resolution or move closer to the router"
                )
        log.info("usable: pids-edge run --source %s", url)
    finally:
        cam.close()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from pids_edge.camera import open_source
    from pids_edge.config import CameraConfig
    from pids_edge.detector import YoloDetector
    from pids_edge.ground import Calibration, GroundPlane
    from pids_edge.pipeline import EdgeNode, run
    from pids_edge.preview import PreviewServer
    from pids_edge.thermal import Mlx90640, ThermalArray

    cfg = EdgeConfig.from_yaml(args.config)
    site = Site.from_yaml(cfg.site)
    if args.source is not None:
        src: int | str = int(args.source) if args.source.isdigit() else args.source
        cfg = cfg.model_copy(
            update={"camera": CameraConfig(**{**cfg.camera.model_dump(), "source": src})}
        )
    detector = YoloDetector(
        cfg.detector.model,
        score_threshold=cfg.detector.score_threshold,
        iou_threshold=cfg.detector.iou_threshold,
        threads=cfg.detector.threads,
    )
    source = open_source(cfg.camera)
    first = source.read(timeout_s=10.0)
    if first is None:
        log.error("camera produced no frames")
        return 1
    ground = GroundPlane(Calibration.load(cfg.ground.calibration), first.size)
    thermal: ThermalArray | None = Mlx90640() if cfg.sensors.thermal.driver == "mlx90640" else None
    node = EdgeNode(cfg, site, detector, ground, thermal=thermal)

    publisher: MqttPublisher | None = None
    if not args.offline:
        try:
            publisher = _publisher(cfg, site)
        except _NoCredentialsError as exc:
            log.error("%s", exc)
            return 2
    gps = _start_gps(cfg, site, publisher)
    ble = _start_ble(cfg, site, publisher)

    preview: PreviewServer | None = None
    if cfg.preview.enabled and not args.no_preview:
        preview = PreviewServer(cfg.preview.host, cfg.preview.port, cfg.preview.jpeg_quality)
        preview.start()
    try:
        run(node, source, publisher, preview, model_name=cfg.detector.model.stem)
    finally:
        if gps:
            gps.stop()
        if ble:
            ble.stop()
    return 0


def cmd_gps(args: argparse.Namespace) -> int:
    """Identify a GPS module (--probe), or stream its fixes to MQTT without a camera."""
    import signal
    import threading

    from pids_edge.gps import candidate_ports, probe

    if args.probe:
        ports = candidate_ports() if args.port == "auto" else [args.port]
        log.info("serial ports to try: %s", ", ".join(ports) or "none found")
        found = probe(ports)
        if found is None:
            log.error(
                "no NMEA GPS found — check the cable/adapter, and that the module's LED "
                "blinks (powered). On macOS a CH340/CP210x adapter may need its driver."
            )
            return 1
        log.info("GPS module on %s at %d baud", found.port, found.baud)
        log.info("%s", found.description)
        log.info(
            "position fix: %s", "yes" if found.has_fix else "not yet (go outdoors, wait 1-2 min)"
        )
        return 0

    cfg = EdgeConfig.from_yaml(args.config)
    if cfg.sensors.gps.driver == "none":
        log.error("sensors.gps.driver is 'none' in %s", args.config)
        return 2
    site = Site.from_yaml(cfg.site)
    try:
        publisher = None if args.offline else _publisher(cfg, site)
    except _NoCredentialsError as exc:
        log.error("%s", exc)
        return 2
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    reader = _start_gps(cfg, site, publisher)
    stop.wait()
    if reader:
        reader.stop()
    if publisher:
        publisher.stop()
    return 0


def cmd_ble(args: argparse.Namespace) -> int:
    """Listen for PIDS badges and print who is heard, how loud (no MQTT)."""
    import signal
    import threading

    from pids_core.badges import BadgeResolver
    from pids_edge.ble import BadgeAggregator, BadgeScanner, site_key_from_env

    cfg = EdgeConfig.from_yaml(args.config)
    site = Site.from_yaml(cfg.site)

    def show(tag: str, rssi: float, at: datetime) -> None:
        log.info("%s  %-16s %6.1f dBm", at.strftime("%H:%M:%S"), tag, rssi)

    resolver = BadgeResolver(site_key_from_env(), site.tags, allow_static=args.allow_static)
    agg = BadgeAggregator(resolver, show, interval_s=1.0)
    scanner = BadgeScanner(agg)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    scanner.start()
    while not stop.wait(10.0):
        log.info(
            "(other BLE adverts: %d, unresolved PIDS ids: %d)", agg.heard_other, agg.unresolved
        )
    scanner.stop()
    return 0


def cmd_badge_code(args: argparse.Namespace) -> int:
    """Manufacturer data for a phone BLE-advertiser app (bench testing; static = replayable)."""
    from pids_core.badges import COMPANY_ID, VERSION_STATIC, badge_secret, payload, static_id
    from pids_edge.ble import site_key_from_env

    cfg = EdgeConfig.from_yaml(args.config)
    site = Site.from_yaml(cfg.site)
    if args.tag not in site.tags:
        log.error("unknown tag %s (known: %s)", args.tag, ", ".join(site.tags))
        return 2
    data = payload(static_id(badge_secret(site_key_from_env(), args.tag)), VERSION_STATIC)
    log.info(
        "advertise manufacturer data — company id 0x%04X, data 0x%s", COMPANY_ID, data.hex().upper()
    )
    log.info(
        "then run the edge with sensors.ble.allow_static: true (bench only: a static id can be replayed)"
    )
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    from pids_edge.calibrate import FloorMarks, interactive

    cfg = EdgeConfig.from_yaml(args.config)
    site = Site.from_yaml(cfg.site)
    calib = interactive(cfg, site, FloorMarks.load(args.marks), args.mode)
    if calib is None:
        log.info("calibration abandoned; nothing written")
        return 1
    out = args.out or cfg.ground.calibration
    calib.save(out)
    log.info(
        "saved %s (%s, RMS %.3f m over %d marks)",
        out,
        calib.method,
        calib.rms_error_m,
        len(calib.points),
    )
    return 0


def cmd_calibrate_pose(args: argparse.Namespace) -> int:
    from pids_edge.calibrate import pose_calibration

    cfg = EdgeConfig.from_yaml(args.config)
    site = Site.from_yaml(cfg.site)
    node = next(n for n in site.config.nodes if n.id == cfg.node_id)
    calib = pose_calibration(
        cfg.node_id,
        (cfg.camera.width, cfg.camera.height),
        position=node.position,
        heading_deg=node.heading_deg if args.heading is None else args.heading,
        height_m=args.height,
        pitch_deg=args.pitch,
        hfov_deg=args.hfov,
    )
    out = args.out or cfg.ground.calibration
    calib.save(out)
    log.info(
        "saved %s (pose estimate, assumed error %.2f m) — refine with markers",
        out,
        calib.rms_error_m,
    )
    return 0


def cmd_markers(args: argparse.Namespace) -> int:
    from pids_edge.calibrate import write_markers

    lo, _, hi = args.ids.partition("-")
    ids = list(range(int(lo), int(hi or lo) + 1))
    for path in write_markers(args.out, ids):
        log.info("wrote %s", path)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser(
        prog="pids-edge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("cameras", help="list camera indices that open").set_defaults(fn=cmd_cameras)

    p = sub.add_parser("run", help="run the edge node")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--source", help="override camera: device index or video file")
    p.add_argument("--offline", action="store_true", help="do not connect to MQTT")
    p.add_argument("--no-preview", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("gps", help="identify a GPS module (--probe) or stream it to MQTT")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--probe", action="store_true", help="find the port and baud, then exit")
    p.add_argument("--port", default="auto")
    p.add_argument("--offline", action="store_true", help="print fixes without MQTT")
    p.set_defaults(fn=cmd_gps)

    p = sub.add_parser("camera-test", help="check a phone or IP camera stream before the demo")
    p.add_argument("url", help="e.g. http://192.168.0.105:8081/stream.mjpg")
    p.add_argument("--frames", type=int, default=60)
    p.set_defaults(fn=cmd_camera_test)

    p = sub.add_parser("ble", help="listen for PIDS badges and print who is heard")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--allow-static", action="store_true")
    p.set_defaults(fn=cmd_ble)

    p = sub.add_parser("badge-code", help="static badge payload for a phone advertiser app")
    p.add_argument("tag")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.set_defaults(fn=cmd_badge_code)

    p = sub.add_parser("calibrate", help="floor homography from markers or clicked tape marks")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--marks", type=Path, required=True, help="floor marks file (site metres)")
    p.add_argument("--mode", choices=["markers", "click"], default="markers")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("calibrate-pose", help="rough homography from the camera's mounting")
    p.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    p.add_argument("--height", type=float, required=True, help="lens height above floor, m")
    p.add_argument("--pitch", type=float, required=True, help="downward tilt from level, degrees")
    p.add_argument("--hfov", type=float, default=70.0, help="horizontal field of view, degrees")
    p.add_argument("--heading", type=float, help="compass heading (default: site node heading)")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_calibrate_pose)

    p = sub.add_parser("markers", help="write printable ArUco floor markers")
    p.add_argument("--out", type=Path, default=Path("markers"))
    p.add_argument("--ids", default="0-5", help="e.g. 0-5")
    p.set_defaults(fn=cmd_markers)

    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
