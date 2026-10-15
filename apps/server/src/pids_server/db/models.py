"""Relational schema (PostgreSQL 17 + PostGIS). Owned by Alembic migrations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        datetime: DateTime(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
    }


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    GUARD = "guard"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


def _enum(e: type[StrEnum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


# --------------------------------------------------------------------- identity


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    tag_id: Mapped[str | None] = mapped_column(
        String(64), comment="cooperative tag this user's phone reports as (guards)"
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class RefreshToken(Base):
    """Opaque, rotating refresh tokens (stored hashed). Reuse of a rotated token
    revokes the whole family — the standard defence against token theft."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")


class PushToken(Base):
    __tablename__ = "push_tokens"

    token: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


# ------------------------------------------------------------------------ sites


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64))
    origin = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(comment="full SiteConfig (local metres)")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Zone(Base):
    __tablename__ = "zones"

    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    geom = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=True), nullable=False)
    actions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Tag(Base):
    __tablename__ = "tags"

    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    authorized: Mapped[bool] = mapped_column(Boolean, default=True)
    home_zone: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# ----------------------------------------------------------------------- alerts


class Alert(Base):
    """One alert episode as raised by the decision core, plus its operator lifecycle."""

    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_site_status_opened", "site_id", "status", "opened_at"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[AlertStatus] = mapped_column(
        _enum(AlertStatus, "alert_status"), default=AlertStatus.OPEN
    )
    level: Mapped[str] = mapped_column(String(16))
    max_level: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer)
    zone_id: Mapped[str | None] = mapped_column(String(64))
    entity_class: Mapped[str] = mapped_column(String(16))
    tag_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    position = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=False)
    last_assessment: Mapped[dict[str, Any]]
    opened_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    cleared_at: Mapped[datetime | None]
    track_lost: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None]
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None]
    resolution_note: Mapped[str | None] = mapped_column(Text)

    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="alert", order_by="AlertEvent.at", lazy="selectin"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime]
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    alert: Mapped[Alert] = relationship(back_populates="events")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = mapped_column(default=utcnow)


# ------------------------------------------------------------------ telemetry


class Observation(Base):
    """1 Hz sample of every assessed entity: replay, incident timelines and
    natural-language queries. Subject to a retention limit (DPDP minimisation)."""

    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_entity_at", "entity_id", "at"),
        Index("ix_observations_at_brin", "at", postgresql_using="brin"),
        ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    at: Mapped[datetime]
    position = mapped_column(Geometry("POINT", srid=4326, spatial_index=True), nullable=False)
    entity_class: Mapped[str] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer)
    zone_id: Mapped[str | None] = mapped_column(String(64))
    tag_id: Mapped[str | None] = mapped_column(String(64))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now(), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(200))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
