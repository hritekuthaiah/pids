from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest

from pids_server.db.models import Role
from pids_server.security import (
    Principal,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    token_digest,
    verify_password,
)

SECRET = "x" * 48
P = Principal(user_id=uuid.uuid4(), role=Role.GUARD, name="G", tag_id="patrol-alpha")


def test_password_hash_round_trip() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", h) == (True, None)
    assert verify_password("wrong", h) == (False, None)
    assert verify_password("anything", "not-a-hash") == (False, None)


def test_access_token_round_trip() -> None:
    token = create_access_token(P, SECRET, timedelta(minutes=5))
    assert decode_access_token(token, SECRET) == P


def test_expired_token_rejected() -> None:
    token = create_access_token(P, SECRET, timedelta(seconds=-60))
    with pytest.raises(TokenError):
        decode_access_token(token, SECRET)


def test_wrong_secret_and_algorithm_none_rejected() -> None:
    token = create_access_token(P, SECRET, timedelta(minutes=5))
    with pytest.raises(TokenError):
        decode_access_token(token, "y" * 48)
    unsigned = jwt.encode({"sub": str(P.user_id), "typ": "access"}, key=None, algorithm="none")
    with pytest.raises(TokenError):
        decode_access_token(unsigned, SECRET)


def test_refresh_token_cannot_be_used_as_access_token() -> None:
    forged = jwt.encode(
        {
            "iss": "pids",
            "sub": str(P.user_id),
            "role": "admin",
            "typ": "refresh",
            "iat": 0,
            "exp": 2**40,
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError, match="not an access token"):
        decode_access_token(forged, SECRET)


def test_token_digest_is_stable_and_not_the_token() -> None:
    assert token_digest("abc") == token_digest("abc")
    assert token_digest("abc") != "abc"
    assert len(token_digest("abc")) == 64


def test_blank_env_values_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from pids_server.settings import Settings

    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "MQTT_SERVER_PASSWORD", "JWT_SECRET"):
        monkeypatch.setenv(key, "test-only-value")
    monkeypatch.setenv("MQTT_CA_FILE", "")
    monkeypatch.setenv("OLLAMA_BASE_URL", "  ")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.mqtt_ca_file is None
    assert s.ollama_base_url is None
