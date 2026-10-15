"""Password hashing, access tokens, refresh tokens and WebSocket tickets.

- Passwords: Argon2id (memory-hard), transparently re-hashed when parameters change.
- Access tokens: short-lived HS256 JWTs carrying role and tag — stateless checks.
- Refresh tokens: opaque random strings stored only as SHA-256 hashes, rotated on
  every use; presenting an already-rotated token revokes the whole family.
- WebSocket tickets: one-time, 30-second tokens fetched over authenticated HTTP,
  so long-lived credentials never appear in a WebSocket URL or proxy log.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from pids_server.db.models import Role

_hasher = PasswordHasher()
_ALGORITHM = "HS256"
_ISSUER = "pids"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Returns (ok, new_hash_if_rehash_needed)."""
    try:
        _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False, None
    return True, (_hasher.hash(password) if _hasher.check_needs_rehash(password_hash) else None)


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    role: Role
    name: str
    tag_id: str | None


def create_access_token(p: Principal, secret: str, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": _ISSUER,
        "sub": str(p.user_id),
        "role": p.role.value,
        "name": p.name,
        "tag": p.tag_id,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(8),
        "typ": "access",
    }
    return jwt.encode(claims, secret, algorithm=_ALGORITHM)


class TokenError(Exception):
    pass


def decode_access_token(token: str, secret: str) -> Principal:
    try:
        c = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            options={"require": ["exp", "iat", "sub", "typ"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if c.get("typ") != "access":
        raise TokenError("not an access token")
    return Principal(
        user_id=uuid.UUID(c["sub"]),
        role=Role(c["role"]),
        name=c.get("name", ""),
        tag_id=c.get("tag"),
    )


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
