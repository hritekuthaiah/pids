"""End-to-end behaviour of the decision engine on hand-built scenarios."""

from __future__ import annotations

from helpers import GpsFactory, TrackFactory, at
from pids_core.baseline import NaiveGeofence
from pids_core.contracts import AlertEventKind, EntityClass, TagRead, ThreatLevel
from pids_core.engine import DecisionEngine
from pids_core.site import Site

DT = 0.5


def run_intruder(engine: DecisionEngine, track_batch: TrackFactory, *, end_north: float = 0.0):
    """Walk straight south from 260 m north of origin at 1.6 m/s, stepping every 0.5 s."""
    events, levels = [], []
    t, north = 0.0, 260.0
    while north > end_north:
        engine.ingest_tracks(track_batch(t, 5.0, north, hits=int(t / DT) + 1))
        r = engine.step(at(t))
        events += r.events
        levels += [a.level for a in r.assessments]
        t += DT
        north -= 1.6 * DT
    return events, levels, t - DT


def test_intruder_warns_before_and_escalates_at_breach(
    site: Site, track_batch: TrackFactory
) -> None:
    engine = DecisionEngine(site)
    events, _, _ = run_intruder(engine, track_batch)
    kinds = [(e.kind, e.level) for e in events]
    assert kinds[0] == (AlertEventKind.RAISED, ThreatLevel.WARNING)
    assert (AlertEventKind.ESCALATED, ThreatLevel.CRITICAL) in kinds
    warn, crit = events[0], next(e for e in events if e.level is ThreatLevel.CRITICAL)
    lead = (crit.at - warn.at).total_seconds()
    assert lead > 10.0, "early warning should precede the breach by a useful margin"
    assert crit.assessment.zone_id == "compound-critical"
    # the breach alert carries an explanation
    assert any(c.log_odds > 0 for c in crit.assessment.contributions)


def test_authorized_patrol_with_gps_tag_does_not_alarm(
    site: Site, track_batch: TrackFactory, gps_fix: GpsFactory
) -> None:
    engine = DecisionEngine(site)
    events = []
    for i in range(240):
        t = i * DT
        north = 200.0 - 0.8 * t  # walks from the warning band into the compound
        engine.ingest_tracks(track_batch(t, 10.0, north, hits=i + 1, anomaly=0.3))
        if i % 2 == 0:
            engine.ingest_gps(gps_fix(t, 11.5, north + 1.0))
        r = engine.step(at(t))
        events += r.events
    assert events == []
    last = r.assessments
    assert len(last) == 1, "camera track and GPS tag are one entity"
    assert last[0].tag_id == "patrol-alpha"
    assert last[0].authorized
    assert "AUTHORIZED_TAG" in last[0].flags


def test_rfid_badge_at_gate_whitelists_the_track(site: Site, track_batch: TrackFactory) -> None:
    engine = DecisionEngine(site)
    for i in range(10):
        t = i * DT
        engine.ingest_tracks(track_batch(t, 1.0, -104.0 + 0.5 * i, node_id="edge-02", hits=i + 1))
        if i == 3:
            engine.ingest_tag_read(
                TagRead(site_id=site.id, reader_id="gate-south", tag_id="badge-0142", at=at(t))
            )
        r = engine.step(at(t))
    a = r.assessments[0]
    assert a.tag_id == "badge-0142"
    assert a.authorized


def test_revoked_badge_is_not_authorized(site: Site, track_batch: TrackFactory) -> None:
    engine = DecisionEngine(site)
    engine.ingest_tracks(track_batch(0, 1.0, -102.0, node_id="edge-02"))
    engine.ingest_tag_read(
        TagRead(site_id=site.id, reader_id="gate-south", tag_id="badge-0999", at=at(0))
    )
    a = engine.step(at(0)).assessments[0]
    assert a.tag_id == "badge-0999"
    assert not a.authorized


def test_spoofed_tag_far_from_the_intruder_does_not_whitelist(
    site: Site, track_batch: TrackFactory, gps_fix: GpsFactory
) -> None:
    """The intruder's cloned tag reports a patrol route 150 m away: no association."""
    engine = DecisionEngine(site)
    events = []
    for i in range(200):
        t = i * DT
        engine.ingest_tracks(track_batch(t, 5.0, 220.0 - 1.4 * t, hits=i + 1))
        if i % 2 == 0:
            engine.ingest_gps(gps_fix(t, -140.0 + 0.5 * t, 90.0))
        events += engine.step(at(t)).events
    assert any(e.level is ThreatLevel.CRITICAL for e in events)


def test_tag_claiming_to_stand_in_view_unseen_becomes_suspect(
    site: Site, gps_fix: GpsFactory
) -> None:
    engine = DecisionEngine(site)
    for i in range(60):
        engine.ingest_gps(gps_fix(i, 0.0, 150.0))  # in edge-01's view, nobody there
        r = engine.step(at(i))
    a = r.assessments[0]
    assert a.spoof_suspicion > 0.5
    assert "SPOOF_SUSPECTED" in a.flags
    assert not any(c.channel == "authorized_tag" and c.log_odds < 0 for c in a.contributions)


def test_asset_leaving_the_armoury_is_a_containment_breach(site: Site, gps_fix: GpsFactory) -> None:
    engine = DecisionEngine(site)
    events = []
    for i in range(80):
        engine.ingest_gps(gps_fix(i, -10.0, 0.0 - 1.0 * i, tag="crate-07"))
        events += engine.step(at(i)).events
    breach = [e for e in events if "CONTAINMENT_BREACH" in e.assessment.flags]
    assert breach
    assert breach[0].level is ThreatLevel.CRITICAL
    assert breach[0].assessment.entity_class is EntityClass.UNKNOWN


def test_intruder_who_vanishes_inside_is_reported_lost(
    site: Site, track_batch: TrackFactory
) -> None:
    engine = DecisionEngine(site)
    _, _, t_end = run_intruder(engine, track_batch, end_north=50.0)
    later = engine.step(at(t_end + 30)).events
    assert [e.kind for e in later] == [AlertEventKind.TRACK_LOST]
    assert later[0].level is ThreatLevel.CRITICAL


def test_dog_in_the_warning_band_vs_naive_baseline(site: Site, track_batch: TrackFactory) -> None:
    engine = DecisionEngine(site)
    naive = NaiveGeofence(site, "line-crossing")
    pids_events, naive_events = [], []
    for i in range(120):
        t = i * DT
        b = track_batch(t, -60.0 + 0.3 * t, 160.0, cls=EntityClass.ANIMAL, conf=0.8, hits=i + 1)
        engine.ingest_tracks(b)
        naive.ingest_tracks(b)
        pids_events += engine.step(at(t)).events
        naive_events += naive.step(at(t)).events
    assert pids_events == []
    assert [e.kind for e in naive_events] == [AlertEventKind.RAISED]


def test_gps_only_baseline_is_blind_to_untagged_intruders(
    site: Site, track_batch: TrackFactory
) -> None:
    naive = NaiveGeofence(site, "gps-only")
    events = []
    for i in range(200):
        t = i * DT
        naive.ingest_tracks(track_batch(t, 5.0, 220.0 - 1.4 * t))
        events += naive.step(at(t)).events
    assert events == []
