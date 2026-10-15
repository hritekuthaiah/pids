"""Integration fixtures: an isolated ``pids_test`` database on the dev/CI stack.

Requires the docker compose stack (``make up``). Tests that use these fixtures are
marked ``integration`` and are skipped automatically if Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from pids_core.site import SiteConfig
from pids_server.admin import _ensure_user
from pids_server.api.main import create_app
from pids_server.db import models as m
from pids_server.db.session import Database
from pids_server.settings import Settings
from pids_server.site_store import upsert_site
from server_helpers import PASSWORD

ROOT = Path(__file__).resolve().parents[3]
TEST_DB = "pids_test"


def _settings() -> Settings:
    return Settings(postgres_db=TEST_DB)


async def _prepare_database(s: Settings) -> None:
    conn = await asyncpg.connect(
        user=s.postgres_user,
        password=s.postgres_password.get_secret_value(),
        host=s.postgres_host,
        port=s.postgres_port,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()
    conn = await asyncpg.connect(
        user=s.postgres_user,
        password=s.postgres_password.get_secret_value(),
        host=s.postgres_host,
        port=s.postgres_port,
        database=TEST_DB,
    )
    try:
        for ext in ("postgis", "vector", "pg_trgm", "pgcrypto"):
            await conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    try:
        s = _settings()
        asyncio.run(_prepare_database(s))
    except (OSError, asyncpg.PostgresError, ValueError) as exc:
        pytest.skip(f"integration stack unavailable: {exc}")
    env = {**os.environ, "POSTGRES_DB": TEST_DB}
    subprocess.run(  # noqa: S603 — fixed argv, test-only
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "apps/server/alembic.ini"),
            "upgrade",
            "head",
        ],
        check=True,
        env=env,
        cwd=ROOT,
    )
    return s


@pytest.fixture
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings.database_url)
    async with database.session() as s:
        await s.execute(
            text(
                "TRUNCATE alert_events, notifications, alerts, observations, audit_log, "
                "push_tokens, refresh_tokens, users, tags, zones, sites CASCADE"
            )
        )
        await upsert_site(s, SiteConfig.from_yaml(ROOT / "config/sites/site-alpha.yaml"))
        await s.commit()
    for email, role, tag in (
        ("admin@test.local", m.Role.ADMIN, None),
        ("operator@test.local", m.Role.OPERATOR, None),
        ("guard@test.local", m.Role.GUARD, "patrol-alpha"),
    ):
        await _ensure_user(database, email, email.split("@")[0], role, tag, PASSWORD)
    yield database
    await database.dispose()


@pytest.fixture
async def client(settings: Settings, db: Database) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with (
        LifespanManager(app) as manager,
        AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as c,
    ):
        await app.state.redis.delete("pids:rl:login:127.0.0.1")
        yield c
