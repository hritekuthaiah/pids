"""Agent layer against real Postgres (pgvector + full text) with a scripted model.

The language model is replaced by a scripted provider that drives the *real* tools;
the embedder by a deterministic bag-of-words hash, so retrieval SQL, persistence,
approvals and RBAC are exercised end to end without network access.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from pids_core.contracts import (
    AlertEvent,
    AlertEventKind,
    ChannelContribution,
    EntityClass,
    GeoPoint,
    ThreatAssessment,
    ThreatLevel,
    ZoneKind,
)
from pids_server.agent import procedures
from pids_server.agent.llm import AgentResult, ToolSpec
from pids_server.api.routes import agent as agent_routes
from pids_server.db.session import Database
from pids_server.decision.recorder import record_event
from server_helpers import bearer, login

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
ALERT_ID = "site-alpha@t/edge-01/7/1"


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * 384
    for word in re.findall(r"[a-z]+", text.lower()):
        vec[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 384] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture(autouse=True)
def offline_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(procedures, "embed", lambda texts: [_hash_embed(t) for t in texts])
    monkeypatch.setattr(procedures, "embed_query", _hash_embed)


class ScriptedAnalyst:
    """Looks at the alert and the procedures through the real tools, then reports."""

    name = "scripted"
    model = "scripted-analyst"

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: Any,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        import json

        alert = json.loads(await call_tool("get_alert", {"alert_id": ALERT_ID}))
        found = json.loads(
            await call_tool(
                "search_procedures", {"query": "critical zone breach unidentified person"}
            )
        )
        ref = found["sections"][0]["id"]
        return AgentResult(
            output={
                "summary": f"{alert['entity_class']} in {alert['zone_id']} at level {alert['level']}.",
                "verdict": "likely_intrusion",
                "confidence": 0.8,
                "likely_cause": "Unauthorised entry.",
                "recommended_actions": [
                    {
                        "action": "Dispatch the nearest guard.",
                        "priority": "now",
                        "rationale": "Breach.",
                        "procedure_ref": ref,
                    },
                    {
                        "action": "Invented step.",
                        "priority": "optional",
                        "rationale": "-",
                        "procedure_ref": "sop-00#9",
                    },
                ],
                "cited_procedures": [ref, "sop-00#9"],
                "incident_report": "Draft.",
            },
            provider=self.name,
            model=self.model,
            tool_calls=[
                {"tool": "get_alert", "input": {}},
                {"tool": "search_procedures", "input": {}},
            ],
        )


class ScriptedTranslator:
    name = "scripted"
    model = "scripted-translator"

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: Any,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        return AgentResult(
            output={
                "intent": "list",
                "since_minutes": 60,
                "levels": ["critical"],
                "zone_ids": ["compound-critical", "not-a-zone"],
                "entity_classes": ["person"],
                "statuses": [],
                "tag_id": "",
                "track_lost_only": False,
                "limit": 10,
            },
            provider=self.name,
            model=self.model,
        )


async def _seed(db: Database) -> None:
    now = datetime.now(UTC)
    a = ThreatAssessment(
        site_id="site-alpha",
        entity_id="edge-01/7",
        at=now,
        entity_class=EntityClass.PERSON,
        position=GeoPoint(lat=13.2625, lon=77.4200),
        velocity=None,
        zone_id="compound-critical",
        zone_kind=ZoneKind.CRITICAL,
        probability=0.97,
        score=97,
        level=ThreatLevel.CRITICAL,
        contributions=[ChannelContribution(channel="zone_critical", value=1.0, log_odds=2.06)],
        flags=["CRITICAL_ZONE_BREACH"],
    )
    ev = AlertEvent(
        alert_id=ALERT_ID,
        kind=AlertEventKind.RAISED,
        level=ThreatLevel.CRITICAL,
        previous_level=None,
        at=now,
        reason="Unidentified person inside the compound",
        assessment=a,
    )
    async with db.session() as s:
        await record_event(s, ev)
        await procedures.index(s, ROOT / "config" / "sops")
        await s.commit()


async def test_triage_end_to_end_with_approvals(
    client: AsyncClient, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db)
    monkeypatch.setattr(agent_routes, "provider_for", lambda settings: ScriptedAnalyst())
    op = await login(client, "operator@test.local")

    status = (await client.get("/api/v1/agent/status", headers=bearer(op))).json()
    assert status["available"] is True
    assert status["procedures_indexed"] >= 15

    r = await client.post(f"/api/v1/alerts/{ALERT_ID}/triage", headers=bearer(op))
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["summary"] == "person in compound-critical at level critical."
    assert report["cited_procedures"][0].startswith(
        "sop-01-intrusion-response#"
    )  # retrieval found the right SOP
    assert "sop-00#9" not in report["cited_procedures"]  # invented citation dropped
    assert report["recommended_actions"][1]["procedure_ref"] == ""
    assert report["tool_calls"] == ["get_alert", "search_procedures"]

    latest = (await client.get(f"/api/v1/alerts/{ALERT_ID}/triage", headers=bearer(op))).json()
    assert latest["id"] == report["id"]

    d = await client.post(
        f"/api/v1/agent/reports/{report['id']}/decisions",
        json={"action_index": 0, "decision": "approved"},
        headers=bearer(op),
    )
    assert d.status_code == 200
    assert d.json()["recommended_actions"][0]["decision"] == "approved"
    assert d.json()["recommended_actions"][1]["decision"] is None
    bad = await client.post(
        f"/api/v1/agent/reports/{report['id']}/decisions",
        json={"action_index": 9, "decision": "approved"},
        headers=bearer(op),
    )
    assert bad.status_code == 422

    guard = await login(client, "guard@test.local")
    assert (
        await client.post(f"/api/v1/alerts/{ALERT_ID}/triage", headers=bearer(guard))
    ).status_code == 403


async def test_procedure_search_is_hybrid(db: Database) -> None:
    async with db.session() as s:
        await procedures.index(s, ROOT / "config" / "sops")
        await s.commit()
        hits = await procedures.search(s, "GPS spoofing tag jumps", k=3)
    assert hits[0]["id"].startswith("sop-04-identity-anomalies#")


async def test_log_question_runs_a_clamped_filter(
    client: AsyncClient, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db)
    monkeypatch.setattr(agent_routes, "provider_for", lambda settings: ScriptedTranslator())
    op = await login(client, "operator@test.local")
    r = await client.post(
        "/api/v1/agent/query",
        json={
            "site_id": "site-alpha",
            "question": "critical people in the compound in the last hour?",
        },
        headers=bearer(op),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["interpreted"]["zone_ids"] == ["compound-critical"]  # unknown zone dropped
    assert body["count"] == 1
    assert body["alerts"][0]["id"] == ALERT_ID
    assert body["answer"] == "1 alert in the last hour (1 critical)."


async def test_no_llm_configured_is_a_clear_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_routes, "provider_for", lambda settings: None)
    op = await login(client, "operator@test.local")
    r = await client.post(
        "/api/v1/agent/query",
        json={"site_id": "site-alpha", "question": "anything today?"},
        headers=bearer(op),
    )
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
