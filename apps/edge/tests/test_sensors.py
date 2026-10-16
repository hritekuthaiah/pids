"""GPS (NMEA) parsing, serial auto-detection and thermal heat confirmation."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from edge_helpers import DEMO_SITE, dets, frame, person_box, true_calibration
from pids_core.geo import heading_deg
from pids_core.site import Site
from pids_edge.config import EdgeConfig, GroundConfig
from pids_edge.detector import Detections
from pids_edge.gps import probe, to_contract
from pids_edge.ground import GroundPlane
from pids_edge.nmea import NmeaError, NmeaState, checksum, split
from pids_edge.pipeline import EdgeNode
from pids_edge.thermal import SyntheticThermal, relative_bearing, warm_at

# The canonical NMEA reference sentences (checksums as published).
RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"


def sentence(body: str) -> str:
    return f"${body}*{checksum(body):02X}"


def svit_epoch(t: str, lat: str = "1310.536", lon: str = "07733.702", q: int = 1) -> list[str]:
    return [
        sentence(f"GNRMC,{t},A,{lat},N,{lon},E,0.4,91.2,161026,,,A"),
        sentence(f"GNGGA,{t},{lat},N,{lon},E,{q},11,0.8,912.0,M,-86.0,M,,"),
    ]


def test_reference_sentences_parse() -> None:
    kind, fields = split(RMC)
    assert kind == "RMC"
    assert fields[1] == "A"
    state = NmeaState()
    assert state.feed(RMC) is None  # waits for the GGA of the same epoch
    fix = state.feed(GGA)
    assert fix is not None
    assert fix.at == datetime(1994, 3, 23, 12, 35, 19, tzinfo=UTC)
    assert fix.lat == pytest.approx(48.1173)
    assert fix.lon == pytest.approx(11.516667, abs=1e-6)
    assert fix.satellites == 8
    assert fix.hdop == pytest.approx(0.9)
    assert fix.altitude_m == pytest.approx(545.4)
    assert fix.speed_ms == pytest.approx(22.4 * 0.514444)
    assert fix.accuracy_m == pytest.approx(3.6)


def test_corrupt_or_foreign_lines_are_rejected() -> None:
    with pytest.raises(NmeaError, match="checksum"):
        split(RMC.replace("4807", "4808"))
    with pytest.raises(NmeaError):
        split("\x00\xffgarbage at the wrong baud rate")
    state = NmeaState()
    state.feed("Hello")
    state.feed(RMC[:-1] + "B")
    assert state.rejected == 2
    assert state.sentences == 0


def test_one_fix_per_epoch_in_any_sentence_order() -> None:
    state = NmeaState()
    rmc, gga = svit_epoch("010203.00")
    assert state.feed(gga) is None
    fix = state.feed(rmc)
    assert fix is not None
    assert fix.lat == pytest.approx(13 + 10.536 / 60)
    assert fix.lon == pytest.approx(77 + 33.702 / 60)
    assert fix.at == datetime(2026, 10, 16, 1, 2, 3, tzinfo=UTC)
    assert state.feed(rmc) is None  # same epoch again: no duplicate
    nxt = [state.feed(s) for s in svit_epoch("010204.00")]
    assert sum(f is not None for f in nxt) == 1


def test_no_fix_is_not_a_position() -> None:
    state = NmeaState()
    void = sentence("GNRMC,010203.00,V,,,,,,,161026,,,N")
    nofix = sentence("GNGGA,010203.00,,,,,0,00,99.9,,M,,M,,")
    assert state.feed(void) is None
    assert state.feed(nofix) is None
    # RMC says valid but GGA reports quality 0: trust the "no fix"
    rmc, _ = svit_epoch("010205.00")
    state.feed(rmc)
    assert state.feed(sentence("GNGGA,010205.00,1310.536,N,07733.702,E,0,03,9.9,,M,,M,,")) is None


def test_module_identity_comes_from_its_own_text() -> None:
    state = NmeaState()
    state.feed(sentence("GPTXT,01,01,02,u-blox ag - www.u-blox.com"))
    state.feed(sentence("GPTXT,01,01,02,HW  UBX-G70xx   00070000 FF7FFFFFo"))
    state.feed(svit_epoch("010203.00")[0])
    desc = state.describe()
    assert "u-blox" in desc
    assert "UBX-G70xx" in desc
    assert "multi-GNSS" in desc


def test_fix_becomes_a_wire_message() -> None:
    state = NmeaState()
    fix = next(f for s in svit_epoch("010203.00") if (f := state.feed(s)))
    msg = to_contract("demo-room", "gps-puck-1", fix)
    assert msg.tag_id == "gps-puck-1"
    assert msg.satellites == 11
    assert msg.accuracy_m == pytest.approx(3.2)
    assert "captured" in msg.trace


def test_probe_finds_a_module_on_a_serial_line() -> None:
    master, slave = os.openpty()
    port = os.ttyname(slave)
    stop = threading.Event()

    def module() -> None:
        k = 0
        while not stop.is_set():
            for s in svit_epoch(f"0102{k % 60:02d}.00"):
                os.write(master, (s + "\r\n").encode())
            k += 1
            time.sleep(0.05)

    t = threading.Thread(target=module, daemon=True)
    t.start()
    try:
        found = probe([port], seconds=0.6)
    finally:
        stop.set()
        t.join()
        os.close(master)
        os.close(slave)
    assert found is not None
    assert found.port == port
    assert found.has_fix


def test_probe_ignores_a_silent_port() -> None:
    master, slave = os.openpty()
    try:
        assert probe([os.ttyname(slave)], seconds=0.3) is None
    finally:
        os.close(master)
        os.close(slave)


# ---------------------------------------------------------------------------
# thermal
# ---------------------------------------------------------------------------


class OnePerson:
    """A detector that always sees one person standing at a floor point."""

    last_inference_ms = 1.0

    def __init__(self, where: tuple[float, float]) -> None:
        self.box = person_box(*where)

    def __call__(self, image: np.ndarray) -> Detections:
        del image
        return dets([self.box], [0.9])


def test_relative_bearing_wraps() -> None:
    assert relative_bearing(125, 140) == pytest.approx(15)
    assert relative_bearing(350, 10) == pytest.approx(20)
    assert relative_bearing(10, 350) == pytest.approx(-20)


def test_warm_at_finds_bodies_and_respects_the_field_of_view() -> None:
    cam = SyntheticThermal()
    cam.bodies = [-12.0]
    img = cam.frame()
    assert img is not None
    assert warm_at(img, -12.0, cam.fov_deg) is True
    assert warm_at(img, 15.0, cam.fov_deg) is False
    assert warm_at(img, 40.0, cam.fov_deg) is None  # outside the array's view


def test_a_single_hot_pixel_is_noise_not_a_person() -> None:
    img = np.full((24, 32), 24.0, np.float32)
    img[10, 16] = 40.0
    assert warm_at(img, 0.0, 55.0) is False


def test_tracks_get_heat_confirmation_from_the_array() -> None:
    site = Site.from_yaml(DEMO_SITE)
    cfg = EdgeConfig(site=DEMO_SITE, node_id="edge-01", ground=GroundConfig(calibration=Path("x")))
    where = (5.0, 2.0)
    cam = SyntheticThermal()
    node = EdgeNode(cfg, site, OnePerson(where), GroundPlane(true_calibration()), thermal=cam)
    here = site.config.nodes[0].position
    cam.bodies = [relative_bearing(125, heading_deg(where[0] - here[0], where[1] - here[1]))]
    for k in range(3):
        batch, _ = node.process(frame(k))
    assert batch.tracks[0].thermal_confirmed is True
    cam.bodies = []
    batch, _ = node.process(frame(3))
    assert batch.tracks[0].thermal_confirmed is False


def test_gps_driver_needs_a_registry_tag() -> None:
    with pytest.raises(ValueError, match="tag_id"):
        EdgeConfig.model_validate(
            {
                "site": str(DEMO_SITE),
                "node_id": "edge-01",
                "ground": {"calibration": "x"},
                "sensors": {"gps": {"driver": "serial"}},
            }
        )
