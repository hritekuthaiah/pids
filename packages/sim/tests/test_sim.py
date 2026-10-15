from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pids_core.baseline import NaiveGeofence
from pids_core.contracts import ZoneKind
from pids_core.engine import DecisionEngine
from pids_core.site import Site
from pids_sim.agents import Role, path
from pids_sim.outcomes import score_run
from pids_sim.runner import frames, ground_truth, run
from pids_sim.scenarios import Family, ScenarioSpec, build

SITE = Site.from_yaml(Path(__file__).resolve().parents[3] / "config/sites/site-alpha.yaml")


def test_path_timing_and_pauses() -> None:
    rng = np.random.default_rng(0)
    p = path([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], 2.0, rng, pauses={1: 3.0})
    assert p.start == 0.0
    assert p.end == pytest.approx(13.0, abs=0.1)  # 5 s + 3 s pause + 5 s
    mid = p.at(6.5)
    assert mid is not None
    assert mid.east == pytest.approx(10.0, abs=0.01)
    assert p.at(-1.0) is None


@pytest.mark.parametrize("family", list(Family))
def test_every_family_builds_with_the_right_threat(family: Family) -> None:
    sc = build(SITE, ScenarioSpec(seed=7, family=family))
    threats = [a for a in sc.agents if a.is_threat]
    assert len(threats) == (0 if family is Family.NORMAL else 1)
    assert any(a.role is Role.PATROL for a in sc.agents)


def test_breaching_threats_actually_breach() -> None:
    for family in (Family.INTRUSION_FOOT, Family.INTRUSION_VEHICLE, Family.SPOOFED_TAG):
        sc = build(SITE, ScenarioSpec(seed=11, family=family))
        truth = ground_truth(SITE, sc)["threat"]
        assert truth.breach_t is not None, family
        assert truth.warning_t is not None
        assert truth.warning_t < truth.breach_t


def test_asset_theft_is_a_containment_breach() -> None:
    sc = build(SITE, ScenarioSpec(seed=3, family=Family.ASSET_THEFT))
    truth = ground_truth(SITE, sc)["threat"]
    assert truth.containment_breach_t is not None


def test_rendering_is_deterministic_per_seed() -> None:
    def digest(seed: int) -> list[tuple[str, int, int]]:
        sc = build(SITE, ScenarioSpec(seed=seed, family=Family.INTRUSION_FOOT, duration_s=60))
        _, stream = frames(SITE, sc)
        return [(f.at.isoformat(), len(f.batches), len(f.fixes)) for f in stream]

    assert digest(5) == digest(5)
    assert digest(5) != digest(6)


def test_spoofed_tag_reports_a_different_path() -> None:
    sc = build(SITE, ScenarioSpec(seed=2, family=Family.SPOOFED_TAG))
    spoofer = next(a for a in sc.agents if a.role is Role.SPOOFER)
    assert spoofer.reported_trajectory is not None
    t = spoofer.trajectory.start + 30
    true_pos, claimed = spoofer.trajectory.at(t), spoofer.reported_trajectory.at(t)
    assert true_pos is not None
    assert claimed is not None
    assert true_pos.distance_to(claimed) > 20


def test_entities_map_back_to_agents() -> None:
    r = run(
        SITE,
        ScenarioSpec(seed=9, family=Family.INTRUSION_FOOT, duration_s=120),
        DecisionEngine(SITE),
    )
    assert "threat" in set(r.entity_agent.values())


def test_baseline_catches_breach_and_pids_suppresses_nuisance_on_same_run() -> None:
    spec = ScenarioSpec(seed=21, family=Family.INTRUSION_FOOT)
    naive = score_run(run(SITE, spec, NaiveGeofence(SITE, "line-crossing")))
    assert all(t.detected for t in naive.threats)
    pids = score_run(run(SITE, spec, DecisionEngine(SITE)))
    assert pids.nuisance_alarms <= naive.nuisance_alarms


def test_ground_truth_zone_entry_order() -> None:
    sc = build(SITE, ScenarioSpec(seed=4, family=Family.INTRUSION_FOOT))
    threat = next(a for a in sc.agents if a.is_threat)
    w = threat.trajectory.first_time_in(SITE.zones, ZoneKind.WARNING)
    c = threat.trajectory.first_time_in(SITE.zones, ZoneKind.CRITICAL)
    assert w is not None
    assert c is not None
    assert w < c
