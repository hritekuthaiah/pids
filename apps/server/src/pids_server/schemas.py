"""API / bus payload schemas shared by the API, decision service and worker."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from geoalchemy2.shape import to_shape
from pydantic import BaseModel, ConfigDict, Field

from pids_core.contracts import ThreatAssessment
from pids_server.db import models as m


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AlertEventOut(Out):
    kind: str
    level: str
    at: datetime
    reason: str
    actor_id: uuid.UUID | None = None


class AlertOut(Out):
    id: str
    site_id: str
    entity_id: str
    status: m.AlertStatus
    level: str
    max_level: str
    score: int
    zone_id: str | None
    entity_class: str
    tag_id: str | None
    reason: str
    lat: float
    lon: float
    opened_at: datetime
    updated_at: datetime
    cleared_at: datetime | None
    track_lost: bool
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    assessment: ThreatAssessment

    @classmethod
    def of(cls, row: m.Alert) -> AlertOut:
        pt = to_shape(row.position)
        return cls(
            id=row.id,
            site_id=row.site_id,
            entity_id=row.entity_id,
            status=row.status,
            level=row.level,
            max_level=row.max_level,
            score=row.score,
            zone_id=row.zone_id,
            entity_class=row.entity_class,
            tag_id=row.tag_id,
            reason=row.reason,
            lat=pt.y,
            lon=pt.x,
            opened_at=row.opened_at,
            updated_at=row.updated_at,
            cleared_at=row.cleared_at,
            track_lost=row.track_lost,
            acknowledged_by=row.acknowledged_by,
            acknowledged_at=row.acknowledged_at,
            resolved_by=row.resolved_by,
            resolved_at=row.resolved_at,
            resolution_note=row.resolution_note,
            assessment=ThreatAssessment.model_validate(row.last_assessment),
        )


class AlertDetailOut(AlertOut):
    events: list[AlertEventOut] = Field(default_factory=list)


class LiveMessage(BaseModel):
    type: Literal["live"] = "live"
    site_id: str
    at: datetime
    entities: list[ThreatAssessment]


class AlertMessage(BaseModel):
    type: Literal["alert"] = "alert"
    event: str
    alert: AlertOut


class Envelope(BaseModel):
    """Anything sent down a WebSocket."""

    type: str
    data: dict[str, Any]
