"""Authentication: login, refresh-token rotation, logout, profile, WebSocket tickets."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from pids_server import bus
from pids_server.api.deps import AnyUser, RedisDep, SessionDep, SettingsDep, audit, client_ip
from pids_server.db import models as m
from pids_server.security import (
    Principal,
    create_access_token,
    hash_password,
    new_opaque_token,
    token_digest,
    verify_password,
)
from pids_server.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_LIMIT_PER_MIN = 10
WS_TICKET_TTL_S = 30
# Constant-time-ish failure path: verify against a dummy hash when the user does
# not exist, so response time does not reveal which emails are registered.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


class LoginIn(BaseModel):
    # Plain string: demo accounts use the reserved .local domain, and a login form
    # only needs to match a stored address, not validate deliverability.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: m.Role
    tag_id: str | None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type, not a secret
    expires_in: int
    user: UserOut


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=256)


class TicketOut(BaseModel):
    ticket: str
    expires_in: int


def _principal(u: m.User) -> Principal:
    return Principal(user_id=u.id, role=u.role, name=u.name, tag_id=u.tag_id)


def _user_out(u: m.User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, tag_id=u.tag_id)


async def _issue(session: SessionDep, settings: Settings, u: m.User, family: uuid.UUID) -> TokenOut:
    refresh = new_opaque_token()
    session.add(
        m.RefreshToken(
            user_id=u.id,
            family=family,
            token_hash=token_digest(refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    return TokenOut(
        access_token=create_access_token(
            _principal(u), settings.jwt_secret.get_secret_value(), ttl
        ),
        refresh_token=refresh,
        expires_in=int(ttl.total_seconds()),
        user=_user_out(u),
    )


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn, request: Request, session: SessionDep, redis: RedisDep, settings: SettingsDep
) -> TokenOut:
    key = f"pids:rl:login:{client_ip(request)}"
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, 60)
    if attempts > LOGIN_LIMIT_PER_MIN:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts")

    user = await session.scalar(select(m.User).where(m.User.email == body.email.lower()))
    ok, rehash = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok or not user.active:
        await audit(session, None, "auth.login_failed", body.email.lower(), request)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if rehash:
        user.password_hash = rehash
    out = await _issue(session, settings, user, uuid.uuid4())
    await audit(session, _principal(user), "auth.login", user.email, request)
    await session.commit()
    return out


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
    row = await session.scalar(
        select(m.RefreshToken).where(m.RefreshToken.token_hash == token_digest(body.refresh_token))
    )
    now = datetime.now(UTC)
    if row is None or row.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    if row.revoked_at is not None:
        # A rotated token was presented again: assume theft, kill the family.
        await session.execute(
            update(m.RefreshToken)
            .where(m.RefreshToken.family == row.family, m.RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await audit(session, None, "auth.refresh_reuse", str(row.user_id))
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token reuse detected")
    if not row.user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account disabled")
    row.revoked_at = now
    out = await _issue(session, settings, row.user, row.family)
    await session.commit()
    return out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshIn, session: SessionDep) -> None:
    row = await session.scalar(
        select(m.RefreshToken).where(m.RefreshToken.token_hash == token_digest(body.refresh_token))
    )
    if row is not None:
        await session.execute(
            update(m.RefreshToken)
            .where(m.RefreshToken.family == row.family, m.RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()


@router.get("/me", response_model=UserOut)
async def me(principal: AnyUser, session: SessionDep) -> UserOut:
    user = await session.get(m.User, principal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return _user_out(user)


@router.post("/ws-ticket", response_model=TicketOut)
async def ws_ticket(principal: AnyUser, redis: RedisDep) -> TicketOut:
    ticket = secrets.token_urlsafe(24)
    await redis.set(
        bus.ws_ticket_key(ticket),
        bus.dumps({"user_id": str(principal.user_id), "role": principal.role.value}),
        ex=WS_TICKET_TTL_S,
    )
    return TicketOut(ticket=ticket, expires_in=WS_TICKET_TTL_S)
