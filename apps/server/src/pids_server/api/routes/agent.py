"""The agent layer's API: triage an alert, decide on its recommendations, ask the log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from pids_server.agent import query as nlq
from pids_server.agent.llm import AgentError
from pids_server.agent.service import provider_for
from pids_server.agent.tools import ToolBox
from pids_server.agent.triage import triage
from pids_server.api.deps import Operator, SessionDep, SettingsDep, audit
from pids_server.db import models as m
from pids_server.site_store import load_site_config

router = APIRouter(tags=["agent"])


class ActionOut(BaseModel):
    action: str
    priority: Literal["now", "soon", "optional"]
    rationale: str
    procedure_ref: str
    decision: Literal["approved", "rejected"] | None = None
    decided_at: datetime | None = None


class TriageOut(BaseModel):
    id: uuid.UUID
    alert_id: str
    provider: str
    model: str
    created_at: datetime
    latency_ms: int
    summary: str
    verdict: Literal["likely_intrusion", "likely_benign", "needs_verification"]
    confidence: float
    likely_cause: str
    recommended_actions: list[ActionOut]
    cited_procedures: list[str]
    incident_report: str
    tool_calls: list[str]

    @classmethod
    def of(cls, r: m.AgentReport) -> TriageOut:
        c = r.content
        actions = []
        for i, a in enumerate(c["recommended_actions"]):
            d = r.decisions.get(str(i), {})
            actions.append(ActionOut(**a, decision=d.get("decision"), decided_at=d.get("at")))
        return cls(
            id=r.id,
            alert_id=r.alert_id or "",
            provider=r.provider,
            model=r.model,
            created_at=r.created_at,
            latency_ms=r.latency_ms,
            summary=c["summary"],
            verdict=c["verdict"],
            confidence=c["confidence"],
            likely_cause=c["likely_cause"],
            recommended_actions=actions,
            cited_procedures=c["cited_procedures"],
            incident_report=c["incident_report"],
            tool_calls=[t["tool"] for t in r.tool_calls.get("calls", [])],
        )


class DecisionIn(BaseModel):
    action_index: Annotated[int, Field(ge=0)]
    decision: Literal["approved", "rejected"]
    note: Annotated[str, Field(max_length=500)] = ""


class QueryIn(BaseModel):
    site_id: str
    question: Annotated[str, Field(min_length=3, max_length=500)]


class QueryAlertOut(BaseModel):
    id: str
    level: str
    zone_id: str | None
    entity_class: str
    status: str
    opened_at: datetime
    reason: str


class QueryOut(BaseModel):
    question: str
    interpreted: dict[str, Any] = Field(
        description="the filter the model chose — shown so a misreading is visible"
    )
    answer: str
    count: int
    alerts: list[QueryAlertOut]
    provider: str
    model: str
    latency_ms: int


class AgentStatusOut(BaseModel):
    available: bool
    provider: str | None
    model: str | None
    procedures_indexed: int


def _require_provider(settings: SettingsDep) -> Any:
    provider = provider_for(settings)
    if provider is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "no LLM is configured: set ANTHROPIC_API_KEY (or OLLAMA_BASE_URL) in .env",
        )
    return provider


@router.get("/agent/status", response_model=AgentStatusOut)
async def agent_status(_: Operator, settings: SettingsDep, session: SessionDep) -> AgentStatusOut:
    provider = provider_for(settings)
    n = await session.scalar(select(func.count()).select_from(m.ProcedureChunk)) or 0
    return AgentStatusOut(
        available=provider is not None,
        provider=provider.name if provider else None,
        model=provider.model if provider else None,
        procedures_indexed=n,
    )


@router.post("/alerts/{alert_id:path}/triage", response_model=TriageOut)
async def triage_alert(
    alert_id: str, principal: Operator, settings: SettingsDep, session: SessionDep, request: Request
) -> TriageOut:
    """Ask the agent for a second opinion on one alert. Read-only; proposes actions."""
    alert = await session.get(m.Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such alert")
    provider = _require_provider(settings)
    tools = ToolBox(session, alert.site_id)
    try:
        report, result, latency = await triage(provider, tools, alert_id, settings.agent_max_turns)
    except AgentError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"agent could not triage: {exc}") from exc
    row = m.AgentReport(
        kind="triage",
        alert_id=alert_id,
        site_id=alert.site_id,
        requested_by=principal.user_id,
        provider=result.provider,
        model=result.model,
        latency_ms=latency,
        content=report.model_dump(),
        tool_calls={
            "calls": result.tool_calls,
            "tokens": {
                "in": result.input_tokens,
                "out": result.output_tokens,
                "cache_read": result.cache_read_tokens,
            },
        },
    )
    session.add(row)
    await audit(session, principal, "agent.triage", alert_id, request, verdict=report.verdict)
    await session.commit()
    return TriageOut.of(row)


@router.get("/alerts/{alert_id:path}/triage", response_model=TriageOut)
async def latest_triage(alert_id: str, _: Operator, session: SessionDep) -> TriageOut:
    row = await session.scalar(
        select(m.AgentReport)
        .where(m.AgentReport.alert_id == alert_id, m.AgentReport.kind == "triage")
        .order_by(m.AgentReport.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no triage for this alert yet")
    return TriageOut.of(row)


@router.post("/agent/reports/{report_id}/decisions", response_model=TriageOut)
async def decide(
    report_id: uuid.UUID,
    body: DecisionIn,
    principal: Operator,
    session: SessionDep,
    request: Request,
) -> TriageOut:
    """An operator approves or rejects one recommended action (human in the loop)."""
    row = await session.get(m.AgentReport, report_id)
    if row is None or row.kind != "triage":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such triage report")
    if body.action_index >= len(row.content["recommended_actions"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no such action")
    row.decisions = {
        **row.decisions,
        str(body.action_index): {
            "decision": body.decision,
            "by": str(principal.user_id),
            "at": datetime.now(UTC).isoformat(),
            "note": body.note,
        },
    }
    await audit(
        session,
        principal,
        f"agent.action.{body.decision}",
        str(report_id),
        request,
        index=body.action_index,
    )
    await session.commit()
    return TriageOut.of(row)


@router.post("/agent/query", response_model=QueryOut)
async def ask_log(
    body: QueryIn, principal: Operator, settings: SettingsDep, session: SessionDep, request: Request
) -> QueryOut:
    """A question about past alerts, answered from the log (the model only picks filters)."""
    provider = _require_provider(settings)
    try:
        cfg = await load_site_config(session, body.site_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    zones = {z.id: z.name for z in cfg.zones}
    try:
        spec, answer, result, latency = await nlq.ask(
            provider, session, body.site_id, zones, body.question, cfg.site.timezone
        )
    except AgentError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"could not interpret the question: {exc}"
        ) from exc
    await audit(session, principal, "agent.query", body.site_id, request, question=body.question)
    await session.commit()
    return QueryOut(
        question=body.question,
        interpreted=spec.model_dump(),
        answer=answer["answer"],
        count=answer["count"],
        alerts=[QueryAlertOut(**a) for a in answer["alerts"]],
        provider=result.provider,
        model=result.model,
        latency_ms=latency,
    )
