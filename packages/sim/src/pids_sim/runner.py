"""Run a scenario through any decision engine and keep the ground truth alongside.

Works with ``pids_core.engine.DecisionEngine`` and the naive baselines alike (they
share the ingest/step interface), which is what makes the comparison fair: same
scenario, same seed, same sensor noise, different decision logic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import numpy as np

from pids_core.contracts import AlertEvent, GpsFix, TagRead, ThreatAssessment, TrackBatch, ZoneKind
from pids_core.engine import StepResult
from pids_core.site import Site
from pids_sim.agents import Role
from pids_sim.scenarios import Scenario, ScenarioSpec, build
from pids_sim.sensors import Frame, Renderer, SensorParams


class Engine(Protocol):
    def ingest_tracks(self, batch: TrackBatch) -> None:
        """Consume one perception cycle from a camera node."""

    def ingest_gps(self, fix: GpsFix, received_at: datetime | None = None) -> None:
        """Consume one cooperative-tag GPS fix."""

    def ingest_tag_read(self, read: TagRead) -> None:
        """Consume one RFID/BLE read at a fixed reader."""

    def step(self, now: datetime) -> StepResult:
        """Advance to ``now`` and return assessments and alert events."""


@dataclass(frozen=True, slots=True)
class AgentTruth:
    agent_id: str
    role: Role
    is_threat: bool
    warning_t: float | None
    breach_t: float | None
    containment_breach_t: float | None


@dataclass(slots=True)
class RunResult:
    spec: ScenarioSpec
    start: datetime
    truth: dict[str, AgentTruth]
    entity_agent: dict[str, str | None]
    events: list[AlertEvent] = field(default_factory=list)
    assessments: list[ThreatAssessment] = field(default_factory=list)

    def agent_of(self, entity_id: str) -> str | None:
        return self.entity_agent.get(entity_id)

    def seconds(self, at: datetime) -> float:
        return (at - self.start).total_seconds()


def ground_truth(site: Site, scenario: Scenario) -> dict[str, AgentTruth]:
    out = {}
    for a in scenario.agents:
        home = site.tags[a.gps_tag].home_zone if a.gps_tag in site.tags else None
        out[a.id] = AgentTruth(
            agent_id=a.id,
            role=a.role,
            is_threat=a.is_threat,
            warning_t=a.trajectory.first_time_in(site.zones, ZoneKind.WARNING),
            breach_t=a.trajectory.first_time_in(site.zones, ZoneKind.CRITICAL),
            containment_breach_t=a.trajectory.first_time_outside(site.zones, home)
            if home
            else None,
        )
    return out


def frames(
    site: Site, scenario: Scenario, params: SensorParams | None = None
) -> tuple[Renderer, Iterator[Frame]]:
    p = params or SensorParams()
    renderer = Renderer(
        site, scenario.agents, np.random.default_rng(scenario.spec.seed + 1), scenario.start, p
    )

    def gen() -> Iterator[Frame]:
        for t in np.arange(0.0, scenario.spec.duration_s, p.frame_dt):
            yield renderer.frame(float(t))

    return renderer, gen()


def run(
    site: Site,
    spec: ScenarioSpec,
    engine: Engine,
    params: SensorParams | None = None,
    keep_assessments: bool = False,
) -> RunResult:
    scenario = build(site, spec)
    renderer, stream = frames(site, scenario, params)
    result = RunResult(
        spec=spec,
        start=scenario.start,
        truth=ground_truth(site, scenario),
        entity_agent=renderer.entity_agent,
    )
    for frame in stream:
        for batch in frame.batches:
            engine.ingest_tracks(batch)
        for fix in frame.fixes:
            engine.ingest_gps(fix, received_at=frame.at)
        for read in frame.reads:
            engine.ingest_tag_read(read)
        step = engine.step(frame.at)
        result.events.extend(step.events)
        if keep_assessments:
            result.assessments.extend(step.assessments)
    return result
