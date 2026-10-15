"""Persist alert-state-machine events and 1 Hz observations."""

from __future__ import annotations

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pids_core.contracts import AlertEvent, AlertEventKind, ThreatAssessment, ThreatLevel
from pids_server.db import models as m


def _point(a: ThreatAssessment) -> object:
    return from_shape(Point(a.position.lon, a.position.lat), srid=4326)


async def record_event(session: AsyncSession, ev: AlertEvent) -> m.Alert:
    a = ev.assessment
    snapshot = a.model_dump(mode="json")
    row = await session.get(m.Alert, ev.alert_id)
    if row is None:
        row = m.Alert(
            id=ev.alert_id,
            site_id=a.site_id,
            entity_id=a.entity_id,
            status=m.AlertStatus.OPEN,
            level=ev.level.value,
            max_level=ev.level.value,
            score=a.score,
            zone_id=a.zone_id,
            entity_class=a.entity_class.value,
            tag_id=a.tag_id,
            reason=ev.reason,
            position=_point(a),
            last_assessment=snapshot,
            opened_at=ev.at,
            updated_at=ev.at,
            track_lost=False,
        )
        session.add(row)
    else:
        row.updated_at = ev.at
        row.last_assessment = snapshot
        row.position = _point(a)
        row.score = a.score
        row.zone_id = a.zone_id or row.zone_id
        row.tag_id = a.tag_id
        if ev.kind is AlertEventKind.ESCALATED:
            row.level = ev.level.value
            row.reason = ev.reason
            if ThreatLevel(ev.level) > ThreatLevel(row.max_level):
                row.max_level = ev.level.value
            if row.status in (m.AlertStatus.RESOLVED, m.AlertStatus.FALSE_ALARM):
                # Escalation after an operator closed it: the threat is back.
                row.status = m.AlertStatus.OPEN
        elif ev.kind is AlertEventKind.CLEARED:
            row.cleared_at = ev.at
        elif ev.kind is AlertEventKind.TRACK_LOST:
            row.track_lost = True
    session.add(
        m.AlertEvent(
            alert_id=ev.alert_id,
            kind=ev.kind.value,
            level=ev.level.value,
            at=ev.at,
            reason=ev.reason,
            assessment=snapshot,
            trace={k: v.isoformat() for k, v in a.trace.items()},
        )
    )
    await session.flush()
    return row


async def record_observations(session: AsyncSession, batch: list[ThreatAssessment]) -> None:
    if not batch:
        return
    await session.execute(
        insert(m.Observation),
        [
            {
                "site_id": a.site_id,
                "entity_id": a.entity_id,
                "at": a.at,
                "position": f"SRID=4326;POINT({a.position.lon} {a.position.lat})",
                "entity_class": a.entity_class.value,
                "level": a.level.value,
                "score": a.score,
                "zone_id": a.zone_id,
                "tag_id": a.tag_id,
            }
            for a in batch
        ],
    )
