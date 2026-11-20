"""Passive BLE badges: rolling identifiers, and linking only on unambiguous evidence."""

from __future__ import annotations

import itertools
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from pids_core.badges import (
    WINDOW_S,
    BadgeLinker,
    BadgeResolver,
    Candidate,
    badge_secret,
    parse_payload,
    payload,
    rolling_id,
    static_id,
    window_of,
)
from pids_core.contracts import (
    EntityClass,
    GeoPoint,
    TagRead,
    ThreatLevel,
    TrackBatch,
    VisionTrack,
)
from pids_core.engine import DecisionEngine
from pids_core.geo import Enu
from pids_core.site import Site

KEY = b"site-key-for-tests-only-32-bytes!"
READER = (0.0, 0.0)
T0 = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)
DEMO = Path(__file__).resolve().parents[3] / "config" / "sites" / "demo-room.yaml"


def rssi(d: float, rng: np.random.Generator) -> float:
    """Log-distance path loss (n = 2) with indoor multipath noise."""
    return -59.0 - 20.0 * math.log10(max(d, 0.3)) + float(rng.normal(0, 3.0))


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------


def test_rolling_id_changes_every_window_and_resolves_with_skew() -> None:
    secret = badge_secret(KEY, "badge-team-1")
    t = 1_792_000_000.0
    w = window_of(t)
    assert rolling_id(secret, w) != rolling_id(secret, w + 1)
    res = BadgeResolver(KEY, ["badge-team-1", "badge-team-2"])
    for k in (-1, 0, 1):
        assert res.resolve(1, rolling_id(secret, w + k), t) == "badge-team-1"
    assert res.resolve(1, rolling_id(secret, w - 3), t) is None  # a replay from 1.5 min ago


def test_another_sites_badge_does_not_resolve() -> None:
    foreign = badge_secret(b"some-other-site-key", "badge-team-1")
    t = 1_792_000_000.0
    assert (
        BadgeResolver(KEY, ["badge-team-1"]).resolve(1, rolling_id(foreign, window_of(t)), t)
        is None
    )


def test_static_ids_only_when_explicitly_allowed() -> None:
    sid = static_id(badge_secret(KEY, "badge-team-2"))
    assert BadgeResolver(KEY, ["badge-team-2"]).resolve(0, sid, 0.0) is None
    assert (
        BadgeResolver(KEY, ["badge-team-2"], allow_static=True).resolve(0, sid, 0.0)
        == "badge-team-2"
    )


def test_payload_round_trip_and_rejection() -> None:
    ident = bytes(range(8))
    assert parse_payload(payload(ident)) == (1, ident)
    assert parse_payload(b"XX" + payload(ident)[2:]) is None
    assert parse_payload(payload(ident)[:-1]) is None
    assert parse_payload(b"PD\x07" + ident) is None


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------


def walk(a: tuple[float, float], b: tuple[float, float], t0: float, t1: float, dt: float = 0.2):
    n = round((t1 - t0) / dt)
    for i in range(n + 1):
        f = i / n
        yield t0 + i * dt, (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def dist(p: tuple[float, float]) -> float:
    return math.hypot(p[0] - READER[0], p[1] - READER[1])


def run(
    paths: dict[str, list[tuple[float, tuple[float, float]]]],
    badge_path: list[tuple[float, tuple[float, float]]],
    seed: int = 0,
) -> BadgeLinker:
    rng = np.random.default_rng(seed)
    linker = BadgeLinker()
    for t, p in badge_path:
        linker.hear("badge-team-1", t, rssi(dist(p), rng))
    now = badge_path[-1][0]
    cands = [
        Candidate(eid, [(t, dist(p)) for t, p in path if now - t <= linker.policy.window_s])
        for eid, path in paths.items()
    ]
    linker.update(now, cands)
    return linker


def test_badge_holder_walking_in_is_linked() -> None:
    holder = list(walk((7.0, -6.0), (2.0, -1.5), 0.0, 8.0))
    linker = run({"cam/1": holder}, holder)
    assert linker.links == {"badge-team-1": "cam/1"}


def test_holder_and_intruder_walking_together_is_ambiguous() -> None:
    holder = list(walk((7.0, -6.0), (2.0, -1.5), 0.0, 8.0))
    beside = list(walk((7.5, -5.5), (2.5, -1.0), 0.0, 8.0))
    linker = run({"cam/1": holder, "cam/2": beside}, holder)
    assert linker.links == {}  # if in doubt, nobody is whitelisted


def test_once_their_paths_diverge_the_right_person_is_linked() -> None:
    holder = list(walk((7.0, -6.0), (1.5, -1.0), 0.0, 8.0))
    intruder = list(walk((6.0, -6.5), (9.0, -6.5), 0.0, 8.0))  # walks across, range ~constant-ish
    linker = run({"cam/1": holder, "cam/2": intruder}, holder)
    assert linker.links == {"badge-team-1": "cam/1"}


def test_badge_behind_a_wall_does_not_whitelist_the_intruder_in_view() -> None:
    holder_outside = [
        (t, (8.0, 3.0)) for t, _ in walk((0, 0), (0, 0), 0.0, 8.0)
    ]  # stationary, unseen
    intruder = list(walk((8.0, -7.0), (2.0, -1.0), 0.0, 8.0))
    linker = run({"cam/2": intruder}, holder_outside)
    assert linker.links == {}


def test_standing_still_gives_no_evidence_but_keeps_an_earned_link() -> None:
    rng = np.random.default_rng(1)
    linker = BadgeLinker()
    path = list(walk((7.0, -6.0), (2.0, -1.5), 0.0, 8.0)) + [
        (8.0 + 0.2 * k, (2.0, -1.5)) for k in range(1, 60)
    ]
    for i, (t, p) in enumerate(path):
        linker.hear("badge-team-1", t, rssi(dist(p), rng))
        if i % 5 == 0:
            cand = Candidate("cam/1", [(tt, dist(pp)) for tt, pp in path[: i + 1] if t - tt <= 10])
            linker.update(t, [cand])
    assert linker.links == {"badge-team-1": "cam/1"}  # held while the guard stands at the desk


def test_a_silent_badge_loses_its_link() -> None:
    holder = list(walk((7.0, -6.0), (2.0, -1.5), 0.0, 8.0))
    linker = run({"cam/1": holder}, holder)
    later = 8.0 + linker.policy.badge_fresh_s + 1
    linker.update(later, [Candidate("cam/1", [(later - 1, 2.9), (later, 2.9)])])
    assert linker.links == {}


def test_two_badges_on_one_person_trusts_neither() -> None:
    rng = np.random.default_rng(2)
    holder = list(walk((7.0, -6.0), (2.0, -1.5), 0.0, 8.0))
    linker = BadgeLinker()
    for t, p in holder:
        linker.hear("badge-team-1", t, rssi(dist(p), rng))
        linker.hear("badge-team-2", t, rssi(dist(p), rng))
    linker.update(8.0, [Candidate("cam/1", [(t, dist(p)) for t, p in holder if 8.0 - t <= 10])])
    assert linker.links == {}


@pytest.mark.parametrize("seed", range(20))
def test_linking_is_robust_to_rssi_noise(seed: int) -> None:
    holder = list(walk((7.0, -6.0), (2.0, -1.5), 0.0, 8.0))
    beside = list(walk((7.5, -5.5), (2.5, -1.0), 0.0, 8.0))
    assert run({"cam/1": holder}, holder, seed).links == {"badge-team-1": "cam/1"}
    assert run({"cam/1": holder, "cam/2": beside}, holder, seed).links == {}


# ---------------------------------------------------------------------------
# engine integration (demo room: BLE scanner at the camera corner)
# ---------------------------------------------------------------------------


def _engine_run(with_companion: bool) -> list:
    site = Site.from_yaml(DEMO)
    reader = site.readers["edge-01-ble"]
    rp = Enu(*reader.position)
    engine = DecisionEngine(site)
    rng = np.random.default_rng(5)
    holder = list(walk((7.5, 0.8), (2.0, 4.5), 0.0, 9.0))
    beside = list(walk((7.9, 1.2), (2.4, 4.9), 0.0, 9.0))
    result = None
    for i, (t, (e, n)) in enumerate(holder):
        at = T0 + timedelta(seconds=t)
        tracks = [_track(site, "1", e, n, i)]
        if with_companion:
            tracks.append(_track(site, "2", *beside[i][1], i))
        engine.ingest_tracks(
            TrackBatch(site_id=site.id, node_id="edge-01", captured_at=at, tracks=tracks)
        )
        d = Enu(e, n).distance_to(rp)
        engine.ingest_tag_read(
            TagRead(
                site_id=site.id,
                reader_id="edge-01-ble",
                tag_id="badge-team-1",
                at=at,
                rssi_dbm=rssi(d, rng),
            )
        )
        result = engine.step(at)
    assert result is not None
    return result.assessments


def _track(site: Site, tid: str, e: float, n: float, i: int) -> VisionTrack:
    lat, lon = site.frame.to_wgs84(Enu(e, n))
    return VisionTrack(
        track_id=tid,
        entity_class=EntityClass.PERSON,
        class_confidence=0.9,
        position=GeoPoint(lat=lat, lon=lon),
        position_sigma_m=0.2,
        hits=i + 1,
    )


def test_engine_whitelists_the_badge_holder_from_ble_alone() -> None:
    (a,) = _engine_run(with_companion=False)
    assert a.tag_id == "badge-team-1"
    assert a.authorized
    assert "ble:badge-team-1" in a.sources


def test_engine_whitelists_nobody_when_an_intruder_walks_alongside() -> None:
    assessments = _engine_run(with_companion=True)
    assert len(assessments) == 2
    assert not any(a.authorized for a in assessments)


Waypoints = list[tuple[float, tuple[float, float]]]


def _along(points: Waypoints, t: float) -> tuple[float, float] | None:
    """Position at ``t`` on a piecewise-linear path, or None while off camera."""
    if not points[0][0] <= t <= points[-1][0]:
        return None
    for (ta, a), (tb, b) in itertools.pairwise(points):
        if ta <= t <= tb:
            f = (t - ta) / (tb - ta) if tb > ta else 0.0
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
    return points[-1][1]


def _scene(tracks: dict[str, Waypoints], badge: Waypoints, t_end: float) -> dict[str, list]:
    """Demo room at 5 Hz; ``tracks`` in batch order. Returns each entity's assessments."""
    site = Site.from_yaml(DEMO)
    rp = Enu(*site.readers["edge-01-ble"].position)
    engine = DecisionEngine(site)
    rng = np.random.default_rng(5)
    seen: dict[str, list] = {}
    for i in range(round(t_end / 0.2) + 1):
        t = round(i * 0.2, 6)
        now = T0 + timedelta(seconds=t)
        batch = [
            _track(site, tid, *p, i)
            for tid, path in tracks.items()
            if (p := _along(path, t + 1e-9)) is not None
        ]
        if batch:
            engine.ingest_tracks(
                TrackBatch(site_id=site.id, node_id="edge-01", captured_at=now, tracks=batch)
            )
        if (b := _along(badge, t + 1e-9)) is not None:
            engine.ingest_tag_read(
                TagRead(
                    site_id=site.id,
                    reader_id="edge-01-ble",
                    tag_id="badge-team-1",
                    at=now,
                    rssi_dbm=rssi(Enu(*b).distance_to(rp), rng),
                )
            )
        for a in engine.step(now).assessments:
            seen.setdefault(a.entity_id.split("/")[-1], []).append(a)
    return seen


HOLDER_IN: Waypoints = [(0.0, (7.5, 0.8)), (9.0, (2.0, 4.5))]


def test_badge_never_passes_to_someone_walking_in_as_its_holder_walks_out() -> None:
    # The holder earns the badge, leaves through the door; 1.5 s later an intruder
    # enters there and heads for the core. Motion alone cannot tell them apart.
    out: Waypoints = [(0.0, (7.5, 0.8)), (9.0, (2.0, 2.0)), (10.0, (1.2, 0.2))]
    seen = _scene(
        {"1": out, "7": [(11.5, (1.2, 0.3)), (16.0, (6.0, 2.0)), (22.0, (6.0, 2.0))]},
        badge=[*out, (12.0, (1.2, -1.5)), (22.0, (1.2, -1.5))],
        t_end=22.0,
    )
    assert any(a.authorized for a in seen["1"]), "the holder earned the badge"
    assert not any(a.authorized for a in seen["7"])
    assert seen["7"][-1].level is ThreatLevel.CRITICAL


def test_a_new_track_beside_the_holder_never_takes_the_badge() -> None:
    # A track listed before the holder's in the same batch must not be stitched to it:
    # the holder is still being tracked, so the newcomer is someone else.
    holder: Waypoints = [*HOLDER_IN, (14.0, (1.0, 5.2))]
    seen = _scene(
        {"2": [(4.0, (7.9, 1.6)), (9.0, (2.4, 4.9)), (14.0, (6.0, 2.0))], "1": holder},
        badge=holder,
        t_end=14.0,
    )
    assert not any(a.authorized for a in seen["2"])
    assert all(a.authorized for a in seen["1"] if a.at >= T0 + timedelta(seconds=4.0))


def test_two_people_lost_together_get_no_badge_on_reacquisition() -> None:
    # Both tracks drop for 0.6 s and come back as new IDs, the intruder's nearest the
    # holder's predicted position: nobody visible is whitelisted, the intruder alarms.
    holder: Waypoints = [*HOLDER_IN, (9.2, (1.8, 4.6))]
    seen = _scene(
        {
            "2": [(4.0, (7.9, 1.6)), (9.0, (2.4, 4.9))],
            "1": holder,
            "3": [(9.8, (1.6, 4.7)), (14.0, (6.0, 2.0)), (20.0, (6.0, 2.0))],
            "4": [(9.8, (2.3, 5.0)), (14.0, (1.0, 5.4)), (20.0, (1.0, 5.4))],
        },
        badge=[*holder, (9.8, (2.3, 5.0)), (14.0, (1.0, 5.4)), (20.0, (1.0, 5.4))],
        t_end=20.0,
    )
    assert not any(a.authorized for a in seen["3"])
    assert seen["3"][-1].level is ThreatLevel.CRITICAL


def test_window_constant_matches_the_phone_side() -> None:
    assert WINDOW_S == 30  # the guard app derives the same identifiers
