from __future__ import annotations

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pids_core.contracts import EntityClass, ThreatLevel, ZoneKind
from pids_core.fusion import TERMS, Evidence, FusionWeights, fuse, terms
from pids_core.scoring import ScoreInput, ScoringPolicy, score

W = FusionWeights()

INTRUDER = Evidence(
    zone_kind=ZoneKind.WARNING,
    entity_class=EntityClass.PERSON,
    class_confidence=0.85,
    track_age_s=10.0,
    thermal_confirmed=True,
    anomaly_score=0.7,
    time_to_breach_s=20.0,
    authorized_tag=False,
    spoof_suspicion=0.0,
)


def p(ev: Evidence) -> float:
    return fuse(ev, W).probability


def test_intruder_scores_high_and_patrol_low() -> None:
    assert p(INTRUDER) > 0.9
    patrol = dataclasses.replace(
        INTRUDER, authorized_tag=True, anomaly_score=0.3, time_to_breach_s=None
    )
    assert p(patrol) < 0.1


def test_animal_is_suppressed() -> None:
    dog = dataclasses.replace(
        INTRUDER, entity_class=EntityClass.ANIMAL, anomaly_score=0.4, time_to_breach_s=None
    )
    assert p(dog) < 0.1


def test_road_vehicle_passing_through_warning_band_does_not_alarm() -> None:
    car = dataclasses.replace(
        INTRUDER,
        entity_class=EntityClass.VEHICLE,
        class_confidence=0.9,
        anomaly_score=0.2,
        time_to_breach_s=None,
    )
    assert p(car) < ScoringPolicy().warning_at


def test_missing_channels_are_neutral_not_negative() -> None:
    blind = dataclasses.replace(INTRUDER, thermal_confirmed=None, anomaly_score=None)
    t = terms(blind)
    assert t["thermal_present"] is None
    assert t["anomaly"] is None
    contrib = {c.channel: c.log_odds for c in fuse(blind, W).contributions}
    assert contrib["thermal_present"] == 0.0
    assert contrib["thermal_absent"] == 0.0
    assert contrib["anomaly"] == 0.0


def test_absent_heat_inside_coverage_is_evidence() -> None:
    cold = dataclasses.replace(INTRUDER, thermal_confirmed=False)
    blind = dataclasses.replace(INTRUDER, thermal_confirmed=None)
    assert p(cold) < p(blind) < p(INTRUDER)


def test_spoofed_tag_loses_its_whitelist() -> None:
    cloned = dataclasses.replace(INTRUDER, authorized_tag=True)
    spoofed = dataclasses.replace(INTRUDER, authorized_tag=True, spoof_suspicion=0.8)
    assert p(spoofed) > p(cloned)
    assert terms(spoofed)["authorized_tag"] == 0.0


def test_strong_behaviour_can_override_a_cloned_tag_in_the_core() -> None:
    cloned = dataclasses.replace(
        INTRUDER, zone_kind=ZoneKind.CRITICAL, authorized_tag=True, anomaly_score=0.9
    )
    assert p(cloned) > 0.5


def test_corroboration_requires_three_independent_channels() -> None:
    assert terms(INTRUDER)["corroboration"] == 1.0
    weak = dataclasses.replace(
        INTRUDER, thermal_confirmed=False, anomaly_score=0.2, time_to_breach_s=None
    )
    assert terms(weak)["corroboration"] == 0.0


def test_contributions_sum_to_logit() -> None:
    r = fuse(INTRUDER, W)
    assert sum(c.log_odds for c in r.contributions) + W.bias == pytest.approx(r.logit)
    assert [c.channel for c in r.contributions] == list(TERMS)


def test_weights_must_cover_every_term() -> None:
    with pytest.raises(ValueError, match="mismatch"):
        FusionWeights(weights={"zone_warning": 1.0})


@given(
    conf=st.floats(0, 1),
    anomaly=st.one_of(st.none(), st.floats(0, 1)),
    age=st.floats(0, 100),
    zone=st.sampled_from([None, ZoneKind.WARNING, ZoneKind.CRITICAL]),
)
def test_monotonic_in_thermal_and_tag(
    conf: float, anomaly: float | None, age: float, zone: ZoneKind | None
) -> None:
    base = Evidence(zone, EntityClass.PERSON, conf, age, None, anomaly, None, False, 0.0)
    assert p(dataclasses.replace(base, thermal_confirmed=True)) >= p(base)
    assert p(dataclasses.replace(base, authorized_tag=True)) <= p(base)
    assert 0.0 <= p(base) <= 1.0


# --------------------------------------------------------------------- scoring

POLICY = ScoringPolicy()


def inp(**kw: object) -> ScoreInput:
    defaults: dict[str, object] = {
        "probability": 0.9,
        "zone_kind": ZoneKind.WARNING,
        "entity_class": EntityClass.PERSON,
        "class_confidence": 0.85,
        "track_age_s": 10.0,
        "authorized": False,
        "spoof_suspicion": 0.0,
        "time_to_breach_s": None,
        "containment_breach": False,
    }
    defaults.update(kw)
    return ScoreInput(**defaults)  # type: ignore[arg-type]


def test_critical_requires_geometric_breach() -> None:
    assert (
        score(inp(probability=0.99, zone_kind=ZoneKind.WARNING), POLICY).level
        is ThreatLevel.WARNING
    )
    s = score(inp(probability=0.99, zone_kind=ZoneKind.CRITICAL), POLICY)
    assert s.level is ThreatLevel.CRITICAL
    assert "CRITICAL_ZONE_BREACH" in s.flags


@pytest.mark.parametrize(
    ("prob", "level"),
    [(0.1, ThreatLevel.NOMINAL), (0.3, ThreatLevel.ELEVATED), (0.6, ThreatLevel.WARNING)],
)
def test_levels_follow_thresholds(prob: float, level: ThreatLevel) -> None:
    assert score(inp(probability=prob), POLICY).level is level


def test_recall_floor_keeps_breach_at_warning() -> None:
    s = score(inp(probability=0.05, zone_kind=ZoneKind.CRITICAL), POLICY)
    assert s.level is ThreatLevel.WARNING
    assert "RECALL_FLOOR" in s.flags


@pytest.mark.parametrize(
    "kw",
    [
        {"authorized": True},
        {"entity_class": EntityClass.ANIMAL},
        {"track_age_s": 2.0},
        {"class_confidence": 0.2},
    ],
)
def test_recall_floor_exemptions(kw: dict[str, object]) -> None:
    s = score(inp(probability=0.05, zone_kind=ZoneKind.CRITICAL, **kw), POLICY)
    assert "RECALL_FLOOR" not in s.flags


def test_spoofed_tag_does_not_exempt_from_recall_floor() -> None:
    s = score(
        inp(probability=0.05, zone_kind=ZoneKind.CRITICAL, authorized=True, spoof_suspicion=0.9),
        POLICY,
    )
    assert s.level is ThreatLevel.WARNING
    assert "SPOOF_SUSPECTED" in s.flags


def test_predicted_breach_raises_early_warning() -> None:
    s = score(inp(probability=0.3, zone_kind=None, time_to_breach_s=12.0), POLICY)
    assert s.level is ThreatLevel.WARNING
    assert "PREDICTED_BREACH" in s.flags
    quiet = score(inp(probability=0.1, zone_kind=None, time_to_breach_s=12.0), POLICY)
    assert quiet.level is ThreatLevel.NOMINAL


def test_containment_breach_is_critical() -> None:
    s = score(
        inp(
            probability=0.01, zone_kind=ZoneKind.CRITICAL, authorized=True, containment_breach=True
        ),
        POLICY,
    )
    assert s.level is ThreatLevel.CRITICAL
    assert "CONTAINMENT_BREACH" in s.flags


def test_threat_level_ordering() -> None:
    assert ThreatLevel.NOMINAL < ThreatLevel.ELEVATED < ThreatLevel.WARNING < ThreatLevel.CRITICAL
    assert max(ThreatLevel.WARNING, ThreatLevel.CRITICAL) is ThreatLevel.CRITICAL
