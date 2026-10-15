from __future__ import annotations

from helpers import at, geo

from pids_core.alerts import AlertPolicy, AlertTracker
from pids_core.contracts import AlertEventKind, EntityClass, TagKind, ThreatAssessment, ThreatLevel
from pids_core.site import Site
from pids_core.spoofing import SpoofMonitor


def assessment(
    site: Site, t: float, level: ThreatLevel, entity: str = "edge-01/1"
) -> ThreatAssessment:
    return ThreatAssessment(
        site_id=site.id,
        entity_id=entity,
        at=at(t),
        entity_class=EntityClass.PERSON,
        position=geo(site, 0, 150),
        velocity=None,
        zone_id="perimeter-warning",
        zone_kind=None,
        probability=0.5,
        score=50,
        level=level,
        contributions=[],
    )


def kinds(events: list) -> list[AlertEventKind]:  # type: ignore[type-arg]
    return [e.kind for e in events]


def test_raise_escalate_and_silence_repeats(site: Site) -> None:
    tr = AlertTracker(AlertPolicy(), site.id)
    assert tr.update(assessment(site, 0, ThreatLevel.ELEVATED)) == []
    raised = tr.update(assessment(site, 1, ThreatLevel.WARNING))
    assert kinds(raised) == [AlertEventKind.RAISED]
    assert raised[0].alert_id == "site-alpha/edge-01/1/1"
    for t in range(2, 10):
        assert tr.update(assessment(site, t, ThreatLevel.WARNING)) == []
    esc = tr.update(assessment(site, 10, ThreatLevel.CRITICAL))
    assert kinds(esc) == [AlertEventKind.ESCALATED]
    assert esc[0].previous_level is ThreatLevel.WARNING
    # dropping back to WARNING then CRITICAL again is not a new escalation
    assert tr.update(assessment(site, 11, ThreatLevel.WARNING)) == []
    assert tr.update(assessment(site, 12, ThreatLevel.CRITICAL)) == []


def test_clear_needs_sustained_quiet(site: Site) -> None:
    tr = AlertTracker(AlertPolicy(clear_hold_s=20), site.id)
    tr.update(assessment(site, 0, ThreatLevel.WARNING))
    assert tr.update(assessment(site, 1, ThreatLevel.NOMINAL)) == []
    assert tr.update(assessment(site, 15, ThreatLevel.NOMINAL)) == []
    # flicker back up resets the hold timer
    assert tr.update(assessment(site, 16, ThreatLevel.WARNING)) == []
    assert tr.update(assessment(site, 17, ThreatLevel.NOMINAL)) == []
    assert tr.update(assessment(site, 36, ThreatLevel.NOMINAL)) == []
    cleared = tr.update(assessment(site, 37, ThreatLevel.NOMINAL))
    assert kinds(cleared) == [AlertEventKind.CLEARED]
    # a new breach afterwards is a new alert
    again = tr.update(assessment(site, 40, ThreatLevel.WARNING))
    assert again[0].alert_id.endswith("/2")


def test_track_lost_is_reported_once_and_not_a_clear(site: Site) -> None:
    tr = AlertTracker(AlertPolicy(lost_after_s=6), site.id)
    tr.update(assessment(site, 0, ThreatLevel.CRITICAL))
    assert tr.sweep(at(5)) == []
    lost = tr.sweep(at(7))
    assert kinds(lost) == [AlertEventKind.TRACK_LOST]
    assert "last seen in perimeter-warning" in lost[0].reason
    assert tr.sweep(at(20)) == []
    assert tr.active("edge-01/1") is ThreatLevel.CRITICAL


# -------------------------------------------------------------------- spoofing


def walk(mon: SpoofMonitor, n: int, start: float = 0.0, speed: float = 1.4) -> float:
    t = start
    for i in range(n):
        t = start + i
        mon.observe_fix(t, speed * t, 0.0, 3.0, 0.9 + 0.05 * (i % 3), received_at=t + 0.2)
    return t


def test_normal_walk_is_not_suspicious() -> None:
    mon = SpoofMonitor(kind=TagKind.PERSON)
    t = walk(mon, 60)
    assert mon.current(t) == 0.0


def test_teleport_raises_suspicion_then_decays() -> None:
    mon = SpoofMonitor(kind=TagKind.PERSON)
    t = walk(mon, 10)
    mon.observe_fix(t + 1, 900.0, 0.0, 3.0, 0.9, received_at=t + 1.2)
    s = mon.current(t + 1.2)
    assert s > 0.2
    assert "physically implausible jump" in mon.reasons
    assert mon.current(t + 600) == 0.0


def test_vehicle_speed_is_plausible_for_a_vehicle_tag_only() -> None:
    car = SpoofMonitor(kind=TagKind.VEHICLE)
    walk(car, 20, speed=20.0)
    assert car.current(20) == 0.0
    person = SpoofMonitor(kind=TagKind.PERSON)
    walk(person, 20, speed=20.0)
    assert person.current(20) > 0.5


def test_replayed_and_future_fixes() -> None:
    mon = SpoofMonitor(kind=TagKind.PERSON)
    walk(mon, 5)
    mon.observe_fix(2.0, 2.8, 0.0, 3.0, 1.0, received_at=5.2)
    assert "out-of-order / replayed fix" in mon.reasons
    mon.observe_fix(30.0, 5.0, 0.0, 3.0, 1.0, received_at=6.0)
    assert "fix timestamp in the future" in mon.reasons


def test_constant_signal_quality_is_a_tell() -> None:
    mon = SpoofMonitor(kind=TagKind.PERSON)
    for i in range(40):
        mon.observe_fix(float(i), 1.4 * i, 0.0, 2.5, 0.8, received_at=i + 0.1)
    assert "signal quality unnaturally constant" in mon.reasons


def test_unseen_in_camera_view() -> None:
    mon = SpoofMonitor(kind=TagKind.PERSON)
    for i in range(20):
        mon.observe_vision(in_view=True, corroborated=False, dt=1.0, now=float(i))
    assert mon.current(20.0) > 0.4
    fresh = SpoofMonitor(kind=TagKind.PERSON)
    for i in range(20):
        fresh.observe_vision(in_view=False, corroborated=False, dt=1.0, now=float(i))
    assert fresh.current(20.0) == 0.0
