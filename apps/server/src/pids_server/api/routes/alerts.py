"""Alert queue and operator lifecycle: acknowledge, resolve, mark false alarm."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from pids_server import bus
from pids_server.api.deps import AnyUser, RedisDep, SessionDep, audit
from pids_server.db import models as m
from pids_server.schemas import AlertDetailOut, AlertEventOut, AlertMessage, AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])

_LEVEL_ORDER = {"nominal": 0, "elevated": 1, "warning": 2, "critical": 3}


class ResolveIn(BaseModel):
    resolution: Literal["resolved", "false_alarm"]
    note: str = Field(default="", max_length=2000)


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    _: AnyUser,
    session: SessionDep,
    site_id: str | None = None,
    status_: Annotated[list[m.AlertStatus] | None, Query(alias="status")] = None,
    since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertOut]:
    q = select(m.Alert).order_by(m.Alert.opened_at.desc()).limit(limit)
    if site_id:
        q = q.where(m.Alert.site_id == site_id)
    if status_:
        q = q.where(m.Alert.status.in_(status_))
    if since:
        q = q.where(m.Alert.opened_at >= since)
    rows = (await session.scalars(q)).all()
    out = [AlertOut.of(r) for r in rows]
    # Open alerts first, most severe first, newest first.
    out.sort(
        key=lambda a: (
            a.status not in (m.AlertStatus.OPEN, m.AlertStatus.ACKNOWLEDGED),
            -_LEVEL_ORDER.get(a.max_level, 0),
            -a.opened_at.timestamp(),
        )
    )
    return out


@router.get("/{alert_id:path}/detail", response_model=AlertDetailOut)
async def get_alert(alert_id: str, _: AnyUser, session: SessionDep) -> AlertDetailOut:
    row = await session.get(m.Alert, alert_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    base = AlertOut.of(row)
    return AlertDetailOut(
        **base.model_dump(),
        events=[AlertEventOut.model_validate(e) for e in row.events],
    )


async def _transition(
    session: SessionDep,
    redis: RedisDep,
    alert_id: str,
    event: str,
    actor: AnyUser,
    request: Request,
    note: str = "",
) -> AlertOut:
    row = await session.get(m.Alert, alert_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    now = datetime.now(UTC)
    if event == "acknowledged":
        if row.status is not m.AlertStatus.OPEN:
            raise HTTPException(status.HTTP_409_CONFLICT, f"alert is {row.status.value}")
        row.status = m.AlertStatus.ACKNOWLEDGED
        row.acknowledged_by, row.acknowledged_at = actor.user_id, now
    else:
        if row.status in (m.AlertStatus.RESOLVED, m.AlertStatus.FALSE_ALARM):
            raise HTTPException(status.HTTP_409_CONFLICT, f"alert is already {row.status.value}")
        row.status = m.AlertStatus(event)
        row.resolved_by, row.resolved_at, row.resolution_note = actor.user_id, now, note or None
        if row.acknowledged_at is None:
            row.acknowledged_by, row.acknowledged_at = actor.user_id, now
    row.updated_at = now
    session.add(
        m.AlertEvent(
            alert_id=alert_id,
            kind=event,
            level=row.level,
            at=now,
            reason=note or f"{event} by {actor.name}",
            actor_id=actor.user_id,
        )
    )
    await audit(session, actor, f"alert.{event}", alert_id, request, note=note)
    await session.commit()
    out = AlertOut.of(row)
    await redis.publish(
        bus.alerts_channel(row.site_id), bus.dumps(AlertMessage(event=event, alert=out))
    )
    return out


@router.post("/{alert_id:path}/acknowledge", response_model=AlertOut)
async def acknowledge(
    alert_id: str, actor: AnyUser, request: Request, session: SessionDep, redis: RedisDep
) -> AlertOut:
    return await _transition(session, redis, alert_id, "acknowledged", actor, request)


@router.post("/{alert_id:path}/resolve", response_model=AlertOut)
async def resolve(
    alert_id: str,
    body: ResolveIn,
    actor: AnyUser,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
) -> AlertOut:
    return await _transition(session, redis, alert_id, body.resolution, actor, request, body.note)
