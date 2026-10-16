"""Camera -> floor calibration (``pids-edge calibrate``).

Three ways to get the homography, from most to least accurate:

* ``markers`` — printed ArUco markers lie on the floor at surveyed points; they are
  found automatically (the centre is the intersection of the marker's diagonals,
  which is exact under perspective). Repeatable and hands-free: re-run it whenever
  the camera is bumped.
* ``click`` — tape crosses at surveyed points; you click each one on a frozen frame.
* ``pose`` — no floor marks at all: tape-measure the camera's height and tilt and
  compute an ideal pinhole homography. Good enough to start; metres-level error.

Each method checks itself: the floor marks' reprojection RMS is printed and stored,
and the site's zones are drawn back onto the camera image for a visual check.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
import yaml
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from pids_core.site import Site
from pids_edge.camera import Frame, LiveCamera
from pids_edge.config import EdgeConfig
from pids_edge.ground import (
    Calibration,
    CalibrationPoint,
    GroundPlane,
    calibration_from,
    fit,
    from_pose,
)
from pids_edge.pipeline import _zone_lines

log = logging.getLogger("pids_edge.calibrate")

ARUCO_DICT = cv2.aruco.DICT_4X4_50
_WINDOW = "PIDS calibration"


class FloorMark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    world: tuple[float, float] = Field(description="site metres (east, north)")
    marker: Annotated[int, Field(ge=0, lt=50)] | None = None


class FloorMarks(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    points: list[FloorMark] = Field(min_length=4)

    @classmethod
    def load(cls, path: Path) -> FloorMarks:
        with path.open(encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))


# ---------------------------------------------------------------------------
# Marker detection
# ---------------------------------------------------------------------------


def marker_centres(image: NDArray[np.uint8]) -> dict[int, tuple[float, float]]:
    """Pixel centre of every ArUco marker in view (diagonal intersection)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(ARUCO_DICT), cv2.aruco.DetectorParameters()
    )
    corners, ids, _ = detector.detectMarkers(gray)
    found: dict[int, tuple[float, float]] = {}
    if not corners:  # nothing in view (OpenCV then returns ids=None)
        return found
    for quad, marker_id in zip(corners, ids.ravel(), strict=True):
        c = quad.reshape(4, 2).astype(np.float64)
        found[int(marker_id)] = _diagonal_intersection(c)
    return found


def _diagonal_intersection(c: NDArray[np.float64]) -> tuple[float, float]:
    p, r = c[0], c[2] - c[0]
    q, s = c[1], c[3] - c[1]
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) < 1e-9:
        m = c.mean(axis=0)
        return float(m[0]), float(m[1])
    t = ((q - p)[0] * s[1] - (q - p)[1] * s[0]) / denom
    x = p + t * r
    return float(x[0]), float(x[1])


def write_markers(out: Path, ids: list[int], size_px: int = 1200) -> list[Path]:
    """Printable marker images (print at 15-20 cm; keep a white border)."""
    out.mkdir(parents=True, exist_ok=True)
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    written: list[Path] = []
    for i in ids:
        marker = cv2.aruco.generateImageMarker(dictionary, i, size_px)
        border = size_px // 6
        page = cv2.copyMakeBorder(
            marker, border, border * 2, border, border, cv2.BORDER_CONSTANT, value=255
        )
        cv2.putText(
            page,
            f"PIDS floor marker {i}  (ArUco 4x4_50) - centre on the surveyed point",
            (border, page.shape[0] - border // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            size_px / 1400,
            0,
            2,
            cv2.LINE_AA,
        )
        path = out / f"marker-{i:02d}.png"
        cv2.imwrite(str(path), page)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# Solving
# ---------------------------------------------------------------------------


def solve(
    node_id: str,
    size: tuple[int, int],
    pairs: list[tuple[FloorMark, tuple[float, float]]],
    method: str,
) -> Calibration:
    pixels = np.array([px for _, px in pairs], dtype=np.float64)
    world = np.array([m.world for m, _ in pairs], dtype=np.float64)
    h, rms = fit(pixels, world)
    return calibration_from(
        node_id=node_id,
        image_size=size,
        homography=h,
        rms_error_m=round(rms, 4),
        method=method,
        created_at=datetime.now(UTC),
        points=[CalibrationPoint(name=m.name, pixel=px, world=m.world) for m, px in pairs],
    )


def from_markers(node_id: str, frames: list[Frame], marks: FloorMarks) -> Calibration:
    """Average each marker's centre over several frames, then fit."""
    seen: dict[int, list[tuple[float, float]]] = {}
    for f in frames:
        for mid, px in marker_centres(f.image).items():
            seen.setdefault(mid, []).append(px)
    by_id = {m.marker: m for m in marks.points if m.marker is not None}
    pairs: list[tuple[FloorMark, tuple[float, float]]] = []
    for mid, pts in sorted(seen.items()):
        if mid in by_id and len(pts) >= max(1, len(frames) // 2):
            arr = np.array(pts)
            pairs.append((by_id[mid], (float(np.median(arr[:, 0])), float(np.median(arr[:, 1])))))
    missing = sorted(set(by_id) - {m.marker for m, _ in pairs if m.marker is not None})
    if len(pairs) < 4:
        raise RuntimeError(f"found {len(pairs)} of the listed markers (need 4); missing {missing}")
    if missing:
        log.warning("markers not seen reliably: %s", missing)
    return solve(node_id, frames[-1].size, pairs, "aruco")


def pose_calibration(
    node_id: str,
    size: tuple[int, int],
    *,
    position: tuple[float, float],
    heading_deg: float,
    height_m: float,
    pitch_deg: float,
    hfov_deg: float,
) -> Calibration:
    h = from_pose(
        image_size=size,
        hfov_deg=hfov_deg,
        position=position,
        height_m=height_m,
        heading_deg=heading_deg,
        pitch_deg=pitch_deg,
    )
    # Unmeasured: a degree of tilt error at a few metres is ~0.1-0.3 m; say so honestly.
    rms = round(0.05 * height_m / max(math.sin(math.radians(max(pitch_deg, 5.0))), 0.1), 3)
    return calibration_from(
        node_id=node_id,
        image_size=size,
        homography=h,
        rms_error_m=rms,
        method="pose",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Visual check
# ---------------------------------------------------------------------------


def overlay(image: NDArray[np.uint8], site: Site, calib: Calibration) -> NDArray[np.uint8]:
    """Zones, a 1 m floor grid and the floor marks, drawn back onto the frame."""
    ground = GroundPlane(calib, (image.shape[1], image.shape[0]))
    img = image.copy()
    xs = [p[0] for z in site.config.zones for p in z.polygon]
    ys = [p[1] for z in site.config.zones for p in z.polygon]
    for e in range(math.floor(min(xs)), math.ceil(max(xs)) + 1):
        _segment(img, ground, (e, min(ys)), (e, max(ys)), (90, 90, 90))
    for n in range(math.floor(min(ys)), math.ceil(max(ys)) + 1):
        _segment(img, ground, (min(xs), n), (max(xs), n), (90, 90, 90))
    colours = {"warning": (31, 138, 255), "critical": (59, 59, 255), "containment": (255, 160, 80)}
    for kind, runs in _zone_lines(site, ground):
        cv2.polylines(
            img, runs, isClosed=False, color=colours[kind.value], thickness=2, lineType=cv2.LINE_AA
        )
    for p in calib.points:
        cv2.drawMarker(
            img, (round(p.pixel[0]), round(p.pixel[1])), (0, 255, 0), cv2.MARKER_CROSS, 18, 2
        )
        back = ground.to_image(*p.world)
        if back:
            cv2.circle(img, (round(back[0]), round(back[1])), 6, (255, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(
            img,
            p.name,
            (round(p.pixel[0]) + 8, round(p.pixel[1]) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )
    cv2.putText(
        img,
        f"{calib.method}: RMS {calib.rms_error_m:.3f} m  (green = clicked/found, magenta = model)",
        (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    return img


def _segment(
    img: NDArray[np.uint8],
    ground: GroundPlane,
    a: tuple[float, float],
    b: tuple[float, float],
    colour: tuple[int, int, int],
) -> None:
    pts = []
    for k in range(41):
        f = k / 40
        px = ground.to_image(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        if px and -5000 < px[0] < 5000 and -5000 < px[1] < 5000:
            pts.append((round(px[0]), round(px[1])))
    if len(pts) > 1:
        cv2.polylines(img, [np.array(pts, np.int32)], False, colour, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Interactive session
# ---------------------------------------------------------------------------


def interactive(config: EdgeConfig, site: Site, marks: FloorMarks, mode: str) -> Calibration | None:
    """Live view → freeze (SPACE) → click marks or detect markers → check → save (y)."""
    cam = LiveCamera(config.camera)
    clicks: list[tuple[float, float]] = []
    frozen: Frame | None = None
    recent: list[Frame] = []
    calib: Calibration | None = None

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        del flags, param
        if (
            event == cv2.EVENT_LBUTTONDOWN
            and frozen is not None
            and calib is None
            and len(clicks) < len(marks.points)
        ):
            clicks.append((float(x), float(y)))

    cv2.namedWindow(_WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(_WINDOW, on_mouse)
    try:
        while True:
            if frozen is None:
                f = cam.read()
                if f is None:
                    continue
                recent = [*recent[-14:], f]
                view = f.image.copy()
                if mode == "markers":
                    for mid, (u, v) in marker_centres(f.image).items():
                        cv2.drawMarker(
                            view, (round(u), round(v)), (0, 255, 0), cv2.MARKER_CROSS, 24, 2
                        )
                        cv2.putText(
                            view,
                            str(mid),
                            (round(u) + 8, round(v) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7,
                            (0, 255, 0),
                            2,
                        )
                hint = "SPACE: freeze and calibrate   Q: quit"
            elif calib is None:
                view = frozen.image.copy()
                for i, (u, v) in enumerate(clicks):
                    cv2.drawMarker(view, (round(u), round(v)), (0, 255, 0), cv2.MARKER_CROSS, 18, 2)
                    cv2.putText(
                        view,
                        marks.points[i].name,
                        (round(u) + 8, round(v) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 0),
                        2,
                    )
                if len(clicks) < len(marks.points):
                    m = marks.points[len(clicks)]
                    hint = f"click mark {m.name} at ({m.world[0]:.2f}, {m.world[1]:.2f}) m   U: undo   ENTER: solve with these   ESC: back"
                else:
                    hint = "all marks clicked - ENTER: solve   U: undo   ESC: back"
            else:
                view = overlay(frozen.image, site, calib)
                hint = "Y: save   N: redo   (zones should sit exactly on the taped floor)"
            cv2.putText(
                view,
                hint,
                (10, view.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )
            cv2.imshow(_WINDOW, view)
            key = cv2.waitKey(15) & 0xFF
            if key in (ord("q"), ord("Q")):
                return None
            if frozen is None and key == ord(" "):
                frozen = recent[-1] if recent else None
                if frozen is not None and mode == "markers":
                    try:
                        calib = from_markers(config.node_id, recent, marks)
                    except RuntimeError as exc:
                        log.error("%s", exc)
                        frozen = None
            elif frozen is not None and calib is None:
                if key in (ord("u"), ord("U")) and clicks:
                    clicks.pop()
                elif key == 27:
                    frozen, clicks = None, []
                elif key in (13, 10) and len(clicks) >= 4:
                    pairs = list(zip(marks.points, clicks, strict=False))
                    try:
                        calib = solve(config.node_id, frozen.size, pairs, "click")
                    except ValueError as exc:
                        log.error("%s", exc)
            elif calib is not None:
                if key in (ord("y"), ord("Y")):
                    return calib
                if key in (ord("n"), ord("N")):
                    calib, frozen, clicks = None, None, []
    finally:
        cam.close()
        cv2.destroyAllWindows()
