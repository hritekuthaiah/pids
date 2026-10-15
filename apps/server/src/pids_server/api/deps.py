"""FastAPI dependencies: settings, DB session, Redis, the authenticated principal."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pids_server.db import models as m
from pids_server.security import Principal, TokenError, decode_access_token
from pids_server.settings import Settings

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.session() as session:
        yield session


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


async def current_principal(
    settings: SettingsDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(creds.credentials, settings.jwt_secret.get_secret_value())
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require(*roles: m.Role) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    async def check(principal: PrincipalDep) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return principal

    return check


Operator = Annotated[Principal, Depends(require(m.Role.ADMIN, m.Role.OPERATOR))]
Admin = Annotated[Principal, Depends(require(m.Role.ADMIN))]
Guard = Annotated[Principal, Depends(require(m.Role.GUARD))]
AnyUser = PrincipalDep


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def audit(
    session: AsyncSession,
    actor: Principal | None,
    action: str,
    target: str,
    request: Request | None = None,
    **detail: Any,
) -> None:
    session.add(
        m.AuditLog(
            actor_id=actor.user_id if actor else None,
            action=action,
            target=target,
            detail=detail,
            ip=client_ip(request) if request else None,
        )
    )
