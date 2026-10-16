"""NMEA 0183 parsing for serial GPS modules (PLT-03).

Nearly every hobby GPS module (u-blox NEO-6M/7M/M8N/M10, Quectel L76/L80, MediaTek,
SiRF-based USB pucks such as the VK-162/BU-353) speaks NMEA 0183 over a serial or
USB-serial link, so one parser covers them all. We read:

* ``RMC`` — validity, position, speed, course, UTC date and time;
* ``GGA`` — fix quality, satellites used, HDOP, altitude;
* ``GSA`` — PDOP/HDOP/VDOP and fix type (2D/3D);
* ``TXT`` — free text, which u-blox and others use to announce hardware and firmware.

Talker ids are ignored (GP = GPS, GN = multi-constellation, GL, GA, GB/BD), and every
sentence must pass its checksum — a serial line at the wrong baud rate produces
plausible-looking garbage, and a corrupt position is worse than none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time

#: User-equivalent range error for an uncorrected consumer receiver, metres. A
#: 1-sigma horizontal accuracy estimate is HDOP x UERE (standard GNSS error model).
UERE_M = 4.0
#: Never claim better than this without RTK/SBAS corrections.
MIN_ACCURACY_M = 2.5

_KNOT_MS = 0.514444


class NmeaError(ValueError):
    """A line that is not a valid NMEA sentence."""


def checksum(body: str) -> int:
    value = 0
    for ch in body:
        value ^= ord(ch)
    return value


def split(line: str) -> tuple[str, list[str]]:
    """Validate one sentence and return ``(type, fields)``, e.g. ``("RMC", [...])``."""
    line = line.strip()
    if not line.startswith(("$", "!")) or "*" not in line:
        raise NmeaError("not an NMEA sentence")
    body, _, given = line[1:].rpartition("*")
    try:
        expected = int(given[:2], 16)
    except ValueError as exc:
        raise NmeaError("bad checksum field") from exc
    if checksum(body) != expected:
        raise NmeaError("checksum mismatch")
    parts = body.split(",")
    if len(parts[0]) < 5:
        raise NmeaError("bad address field")
    # "GPRMC" -> "RMC"; proprietary "PUBX" sentences keep their full name.
    kind = parts[0] if parts[0].startswith("P") else parts[0][2:]
    return kind, parts[1:]


def _coord(value: str, hemi: str) -> float | None:
    """``ddmm.mmmm`` / ``dddmm.mmmm`` + hemisphere -> signed decimal degrees."""
    if not value or not hemi:
        return None
    dot = value.find(".")
    head = dot if dot >= 0 else len(value)
    degrees = float(value[: head - 2])
    minutes = float(value[head - 2 :])
    if minutes >= 60.0:
        raise NmeaError("minutes out of range")
    out = degrees + minutes / 60.0
    return -out if hemi in ("S", "W") else out


def _float(value: str) -> float | None:
    return float(value) if value else None


def _time(value: str) -> time | None:
    if len(value) < 6:
        return None
    whole, _, frac = value.partition(".")
    micro = int((frac + "000000")[:6]) if frac else 0
    return time(int(whole[0:2]), int(whole[2:4]), int(whole[4:6]), micro, tzinfo=UTC)


def _date(value: str) -> date | None:
    if len(value) != 6:
        return None
    yy = int(value[4:6])
    return date(2000 + yy if yy < 80 else 1900 + yy, int(value[2:4]), int(value[0:2]))


@dataclass(frozen=True, slots=True)
class Fix:
    """A validated position epoch."""

    at: datetime
    lat: float
    lon: float
    hdop: float | None
    satellites: int | None
    speed_ms: float | None
    course_deg: float | None
    altitude_m: float | None
    quality: int

    @property
    def accuracy_m(self) -> float:
        """1-sigma horizontal error estimate: HDOP x UERE, floored."""
        if self.hdop is None:
            return 10.0  # no geometry reported: be honest about not knowing
        return max(MIN_ACCURACY_M, self.hdop * UERE_M)


@dataclass
class NmeaState:
    """Merges the sentences of each epoch into one fix.

    A receiver emits RMC, GGA, GSA... per epoch, each carrying part of the picture;
    ``feed`` returns a ``Fix`` once per epoch, when it has a valid RMC and the GGA of
    the same time (or the next epoch begins without one).
    """

    texts: list[str] = field(default_factory=list)
    talkers: set[str] = field(default_factory=set)
    sentences: int = 0
    rejected: int = 0
    _day: date | None = None
    _rmc: Fix | None = None
    _gga: dict[str, float | int | None] = field(default_factory=dict)
    _gga_time: time | None = None
    _hdop_gsa: float | None = None
    _emitted: datetime | None = None

    def feed(self, line: str) -> Fix | None:
        try:
            kind, f = split(line)
        except NmeaError:
            self.rejected += 1
            return None
        self.sentences += 1
        self.talkers.add(line.strip()[1:3])
        try:
            if kind == "RMC":
                return self._on_rmc(f)
            if kind == "GGA":
                return self._on_gga(f)
            if kind == "GSA" and len(f) > 15:
                self._hdop_gsa = _float(f[15])
            elif kind == "TXT" and len(f) >= 4:
                self.texts.append(f[3])
        except (ValueError, IndexError):
            self.rejected += 1
        return None

    def _on_rmc(self, f: list[str]) -> Fix | None:
        t, valid, day = _time(f[0]), f[1] == "A", _date(f[8])
        if day is not None:
            self._day = day
        lat, lon = _coord(f[2], f[3]), _coord(f[4], f[5])
        if not valid or t is None or self._day is None or lat is None or lon is None:
            self._rmc = None
            return None
        speed = _float(f[6])
        self._rmc = Fix(
            at=datetime.combine(self._day, t),
            lat=lat,
            lon=lon,
            hdop=None,
            satellites=None,
            speed_ms=speed * _KNOT_MS if speed is not None else None,
            course_deg=_float(f[7]),
            altitude_m=None,
            quality=1,
        )
        return self._complete()

    def _on_gga(self, f: list[str]) -> Fix | None:
        self._gga_time = _time(f[0])
        self._gga = {
            "quality": int(f[5] or 0),
            "satellites": int(f[6]) if f[6] else None,
            "hdop": _float(f[7]),
            "altitude_m": _float(f[8]),
        }
        return self._complete()

    def _complete(self) -> Fix | None:
        rmc = self._rmc
        if rmc is None or self._gga_time is None or self._gga_time != rmc.at.timetz():
            return None
        if self._emitted == rmc.at:
            return None
        quality = int(self._gga.get("quality") or 0)
        if quality == 0:
            return None  # receiver says no fix, whatever RMC claims
        sats = self._gga.get("satellites")
        hdop = self._gga.get("hdop")
        alt = self._gga.get("altitude_m")
        fix = replace(
            rmc,
            hdop=float(hdop) if hdop is not None else self._hdop_gsa,
            satellites=int(sats) if sats is not None else None,
            altitude_m=float(alt) if alt is not None else None,
            quality=quality,
        )
        if not (math.isfinite(fix.lat) and math.isfinite(fix.lon)):
            return None
        self._emitted = rmc.at
        return fix

    def describe(self) -> str:
        """What we can tell about the receiver from its own output."""
        hints = [t for t in self.texts if t]
        names = {
            "GP": "GPS",
            "GN": "multi-GNSS",
            "GL": "GLONASS",
            "GA": "Galileo",
            "GB": "BeiDou",
            "BD": "BeiDou",
        }
        constellations = sorted(names.get(t, t) for t in self.talkers)
        parts = [f"talkers: {', '.join(constellations) or 'none'}"]
        if hints:
            parts.append("module says: " + " | ".join(dict.fromkeys(hints)))
        return "; ".join(parts)
