"""Serial GPS module driver: find the port, find the baud rate, stream fixes.

Plug-and-play on purpose: USB GPS pucks and USB-serial adapters appear under
different names per OS and chip (``/dev/cu.usbserial-*``, ``/dev/cu.usbmodem*``,
``/dev/ttyUSB0``, ``/dev/ttyACM0``), and modules ship at 4800, 9600 or 38400 baud.
``probe`` tries each candidate and keeps the first that yields checksum-valid NMEA,
so nobody has to know their module's settings — ``pids-edge gps --probe`` also
prints what the module says about itself.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import serial

from pids_core.contracts import GeoPoint, GpsFix
from pids_edge.nmea import Fix, NmeaState

log = logging.getLogger("pids_edge.gps")

BAUD_RATES = (9600, 38400, 4800, 115200, 57600, 19200)
_PATTERNS = {
    "darwin": ("cu.usbserial*", "cu.usbmodem*", "cu.SLAB_USBtoUART*", "cu.wchusbserial*"),
    "linux": ("ttyUSB*", "ttyACM*", "serial0", "ttyAMA0"),
}


def candidate_ports() -> list[str]:
    patterns = _PATTERNS.get(sys.platform, _PATTERNS["linux"])
    return sorted({str(p) for pattern in patterns for p in Path("/dev").glob(pattern)})


@dataclass(frozen=True, slots=True)
class Probe:
    port: str
    baud: int
    description: str
    has_fix: bool


def _lines(port: serial.Serial) -> Iterator[str]:
    buf = b""
    while True:
        chunk = port.read(256)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            yield raw.decode("ascii", errors="replace")


def probe(ports: list[str] | None = None, seconds: float = 2.5) -> Probe | None:
    """First (port, baud) that speaks valid NMEA; listens a little longer for a fix."""
    for port in ports if ports is not None else candidate_ports():
        for baud in BAUD_RATES:
            try:
                with serial.Serial(port, baud, timeout=0.5) as ser:
                    state = NmeaState()
                    fixed = False
                    deadline = time.monotonic() + seconds
                    for line in _lines(ser):
                        fixed |= state.feed(line) is not None
                        if time.monotonic() > deadline:
                            break
                    if state.sentences >= 3 and state.sentences > state.rejected:
                        if not fixed:  # valid NMEA: give the receiver a moment more
                            for line in _lines(ser):
                                fixed |= state.feed(line) is not None
                                if fixed or time.monotonic() > deadline + 3:
                                    break
                        return Probe(port, baud, state.describe(), fixed)
            except (serial.SerialException, OSError) as exc:
                log.debug("%s @ %d: %s", port, baud, exc)
                break  # port unusable at any baud
    return None


class GpsReader:
    """Streams fixes from a serial module on a thread, reconnecting if unplugged."""

    def __init__(
        self,
        on_fix: Callable[[Fix], None],
        *,
        port: str = "auto",
        baud: int | None = None,
    ) -> None:
        self._on_fix = on_fix
        self._port = port
        self._baud = baud
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="gps", daemon=True)
        self.state = NmeaState()
        self.last_fix: Fix | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _resolve(self) -> tuple[str, int] | None:
        if self._port != "auto" and self._baud:
            return self._port, self._baud
        found = probe([self._port] if self._port != "auto" else None)
        if found is None:
            return None
        log.info("GPS on %s @ %d baud (%s)", found.port, found.baud, found.description)
        return found.port, found.baud

    def _loop(self) -> None:
        while not self._stop.is_set():
            target = self._resolve()
            if target is None:
                log.warning("no GPS module found; retrying in 5 s")
                self._stop.wait(5.0)
                continue
            try:
                with serial.Serial(target[0], target[1], timeout=1.0) as ser:
                    for line in _lines(ser):
                        if self._stop.is_set():
                            return
                        fix = self.state.feed(line)
                        if fix is not None:
                            self.last_fix = fix
                            self._on_fix(fix)
            except (serial.SerialException, OSError) as exc:
                log.warning("GPS link lost (%s); reconnecting", exc)
                self._stop.wait(1.0)


def to_contract(site_id: str, tag_id: str, fix: Fix) -> GpsFix:
    """The wire message for one fix. ``at`` is the receiver's own (GPS-disciplined) time."""
    return GpsFix(
        site_id=site_id,
        tag_id=tag_id,
        at=fix.at,
        position=GeoPoint(lat=fix.lat, lon=fix.lon),
        accuracy_m=round(fix.accuracy_m, 2),
        hdop=fix.hdop,
        satellites=fix.satellites,
        trace={"captured": datetime.now(UTC)},
    )
