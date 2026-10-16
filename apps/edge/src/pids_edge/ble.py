"""BLE badge scanner: hears passive badges (team phones) and reports ``TagRead``s (ADR-0012).

Scans continuously with ``bleak`` (CoreBluetooth on macOS, BlueZ on Linux), keeps only
advertisements carrying a PIDS payload (manufacturer data, company id 0xFFFF, magic
``PD``), resolves each rolling identifier to a tag id, and emits at most one read per
badge per ``interval_s`` carrying the mean RSSI of what was heard — smoothing multipath
spikes before the decision core correlates RSSI with motion.

macOS gives no MAC addresses, which is fine: identity lives in the payload, never in the
radio address (phones randomise those anyway).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pids_core.badges import COMPANY_ID, BadgeResolver, parse_payload

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

log = logging.getLogger("pids_edge.ble")

OnRead = Callable[[str, float, datetime], None]


def site_key_from_env(var: str = "PIDS_BADGE_KEY") -> bytes:
    raw = os.environ.get(var, "")
    if not raw:
        raise RuntimeError(f"{var} is not set (it lives in .env; `make env-sync` adds it)")
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode()


class BadgeAggregator:
    """Collects raw advertisements and emits smoothed reads per badge (pure; tested)."""

    def __init__(self, resolver: BadgeResolver, on_read: OnRead, interval_s: float = 0.4) -> None:
        self._resolver = resolver
        self._on_read = on_read
        self._interval = interval_s
        self._pending: dict[str, list[float]] = defaultdict(list)
        self._last_emit: dict[str, float] = {}
        self.heard_other = 0
        self.unresolved = 0

    def advert(self, manufacturer_data: dict[int, bytes], rssi: float, t: float) -> str | None:
        data = manufacturer_data.get(COMPANY_ID)
        parsed = parse_payload(data) if data is not None else None
        if parsed is None:
            self.heard_other += 1
            return None
        tag = self._resolver.resolve(parsed[0], parsed[1], t)
        if tag is None:
            self.unresolved += 1  # expired (replayed?), foreign site, or unknown badge
            return None
        self._pending[tag].append(rssi)
        if t - self._last_emit.get(tag, -1e9) >= self._interval:
            samples = self._pending.pop(tag)
            self._last_emit[tag] = t
            self._on_read(tag, sum(samples) / len(samples), datetime.fromtimestamp(t, UTC))
        return tag


class BadgeScanner:
    """Runs a bleak scanner on its own thread and event loop."""

    def __init__(self, aggregator: BadgeAggregator) -> None:
        self._agg = aggregator
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ble", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)

    def _on_advert(self, device: BLEDevice, adv: AdvertisementData) -> None:
        del device
        self._agg.advert(dict(adv.manufacturer_data), float(adv.rssi), time.time())

    def _run(self) -> None:
        asyncio.run(self._scan())

    async def _scan(self) -> None:
        from bleak import BleakScanner
        from bleak.exc import BleakError

        while not self._stop.is_set():
            try:
                async with BleakScanner(detection_callback=self._on_advert):
                    log.info("BLE scanning for PIDS badges")
                    await asyncio.to_thread(self._stop.wait)  # a threading.Event: set by stop()
            except (BleakError, OSError) as exc:
                log.warning(
                    "BLE scanner unavailable (%s) — is Bluetooth on and allowed for this app? "
                    "retrying in 5 s",
                    exc,
                )
                await asyncio.sleep(5.0)
