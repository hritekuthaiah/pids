"""BLE badge scanning: payload filtering, resolution and RSSI smoothing (no radio needed)."""

from __future__ import annotations

from datetime import datetime

import pytest

from pids_core.badges import (
    COMPANY_ID,
    VERSION_STATIC,
    BadgeResolver,
    badge_secret,
    payload,
    rolling_id,
    static_id,
    window_of,
)
from pids_edge.ble import BadgeAggregator, site_key_from_env

KEY = bytes.fromhex("11" * 32)
TAGS = ["badge-team-1", "badge-team-2"]


def _agg(**kw: object) -> tuple[BadgeAggregator, list[tuple[str, float, datetime]]]:
    out: list[tuple[str, float, datetime]] = []
    agg = BadgeAggregator(BadgeResolver(KEY, TAGS, **kw), lambda *a: out.append(a), interval_s=0.4)  # type: ignore[arg-type]
    return agg, out


def test_pids_badges_are_resolved_and_smoothed() -> None:
    agg, out = _agg()
    t = 1_792_000_000.0
    adv = {COMPANY_ID: payload(rolling_id(badge_secret(KEY, "badge-team-1"), window_of(t)))}
    for k, r in enumerate([-60.0, -62.0, -64.0, -70.0]):
        assert agg.advert(adv, r, t + 0.1 * k) == "badge-team-1"
    assert len(out) == 1  # one smoothed read per 0.4 s
    agg.advert(adv, -66.0, t + 0.45)
    assert len(out) == 2
    assert out[1][1] == pytest.approx((-62 - 64 - 70 - 66) / 4)


def test_other_devices_and_stale_ids_are_ignored() -> None:
    agg, out = _agg()
    t = 1_792_000_000.0
    agg.advert({0x004C: b"\x02\x15apple-ibeacon-stuff"}, -50, t)  # an iPhone nearby
    agg.advert({}, -50, t)
    old = rolling_id(badge_secret(KEY, "badge-team-2"), window_of(t) - 5)  # replayed
    agg.advert({COMPANY_ID: payload(old)}, -50, t)
    assert out == []
    assert agg.heard_other == 2
    assert agg.unresolved == 1


def test_static_bench_ids_need_an_explicit_opt_in() -> None:
    adv = {COMPANY_ID: payload(static_id(badge_secret(KEY, "badge-team-2")), VERSION_STATIC)}
    strict, out = _agg()
    strict.advert(adv, -55, 0.0)
    assert out == []
    bench, out = _agg(allow_static=True)
    bench.advert(adv, -55, 0.0)
    assert out[0][0] == "badge-team-2"


def test_site_key_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIDS_BADGE_KEY", "ab" * 32)
    assert site_key_from_env() == bytes.fromhex("ab" * 32)
    monkeypatch.delenv("PIDS_BADGE_KEY")
    with pytest.raises(RuntimeError, match="PIDS_BADGE_KEY"):
        site_key_from_env()
