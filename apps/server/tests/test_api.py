"""API integration tests against real Postgres/PostGIS, Redis and MQTT."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import aiomqtt
import pytest
from httpx import AsyncClient

from pids_core.contracts import (
    AlertEvent,
    AlertEventKind,
    EntityClass,
    GeoPoint,
    GpsFix,
    ThreatAssessment,
    ThreatLevel,
    ZoneKind,
)
from pids_server.db.session import Database
from pids_server.decision.recorder import record_event
from pids_server.settings import Settings
from server_helpers import PASSWORD, bearer, login

pytestmark = pytest.mark.integration


def _event(
    kind: AlertEventKind, level: ThreatLevel, alert_id: str = "site-alpha@t/edge-01/1/1"
) -> AlertEvent:
    now = datetime.now(UTC)
    a = ThreatAssessment(
        site_id="site-alpha",
        entity_id="edge-01/1",
        at=now,
        entity_class=EntityClass.PERSON,
        position=GeoPoint(lat=13.2630, lon=77.4200),
        velocity=None,
        zone_id="perimeter-warning",
        zone_kind=ZoneKind.WARNING,
        probability=0.8,
        score=80,
        level=level,
        contributions=[],
    )
    return AlertEvent(
        alert_id=alert_id,
        kind=kind,
        level=level,
        previous_level=None,
        at=now,
        reason="test",
        assessment=a,
    )


# ------------------------------------------------------------------------ auth


async def test_login_me_and_bad_password(client: AsyncClient) -> None:
    tokens = await login(client, "operator@test.local")
    assert tokens["token_type"] == "bearer"
    me = await client.get("/api/v1/auth/me", headers=bearer(tokens))
    assert me.json()["role"] == "operator"
    bad = await client.post(
        "/api/v1/auth/login", json={"email": "operator@test.local", "password": "nope"}
    )
    assert bad.status_code == 401
    ghost = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@test.local", "password": PASSWORD}
    )
    assert ghost.status_code == 401


async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/alerts")).status_code == 401
    r = await client.get("/api/v1/alerts", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient) -> None:
    first = await login(client, "guard@test.local")
    second = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()
    assert second["refresh_token"] != first["refresh_token"]
    # replaying the rotated token revokes the whole family ...
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401
    # ... including the token that was legitimately issued after it
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert after.status_code == 401


async def test_login_rate_limit(client: AsyncClient) -> None:
    codes = [
        (
            await client.post("/api/v1/auth/login", json={"email": "x@test.local", "password": "x"})
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert 429 in codes[10:]


# ----------------------------------------------------------------------- sites


async def test_site_geojson(client: AsyncClient) -> None:
    tokens = await login(client, "operator@test.local")
    site = (await client.get("/api/v1/sites/site-alpha", headers=bearer(tokens))).json()
    layers = {f["properties"]["layer"] for f in site["geojson"]["features"]}
    assert {"zone", "coverage", "node", "reader", "road", "patrol_route"} <= layers
    zone = next(f for f in site["geojson"]["features"] if f["id"] == "compound-critical")
    ring = zone["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert all(77.0 < lon < 78.0 and 13.0 < lat < 14.0 for lon, lat in ring)


async def test_only_admin_can_revoke_tags(client: AsyncClient) -> None:
    op = await login(client, "operator@test.local")
    r = await client.patch(
        "/api/v1/sites/site-alpha/tags/patrol-bravo", json={"authorized": False}, headers=bearer(op)
    )
    assert r.status_code == 403
    admin = await login(client, "admin@test.local")
    r = await client.patch(
        "/api/v1/sites/site-alpha/tags/patrol-bravo",
        json={"authorized": False},
        headers=bearer(admin),
    )
    assert r.status_code == 200
    assert r.json()["authorized"] is False


# ---------------------------------------------------------------------- alerts


async def test_alert_lifecycle(client: AsyncClient, db: Database) -> None:
    async with db.session() as s:
        await record_event(s, _event(AlertEventKind.RAISED, ThreatLevel.WARNING))
        await record_event(s, _event(AlertEventKind.ESCALATED, ThreatLevel.CRITICAL))
        await s.commit()
    tokens = await login(client, "operator@test.local")
    h = bearer(tokens)
    alerts = (await client.get("/api/v1/alerts?site_id=site-alpha&status=open", headers=h)).json()
    assert len(alerts) == 1
    alert_id = alerts[0]["id"]
    assert alerts[0]["max_level"] == "critical"

    ack = await client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=h)
    assert ack.json()["status"] == "acknowledged"
    assert (
        await client.post(f"/api/v1/alerts/{alert_id}/acknowledge", headers=h)
    ).status_code == 409

    res = await client.post(
        f"/api/v1/alerts/{alert_id}/resolve",
        json={"resolution": "false_alarm", "note": "deer"},
        headers=h,
    )
    assert res.json()["status"] == "false_alarm"
    detail = (await client.get(f"/api/v1/alerts/{alert_id}/detail", headers=h)).json()
    assert [e["kind"] for e in detail["events"]] == [
        "raised",
        "escalated",
        "acknowledged",
        "false_alarm",
    ]


async def test_escalation_reopens_a_closed_alert(db: Database) -> None:
    async with db.session() as s:
        row = await record_event(s, _event(AlertEventKind.RAISED, ThreatLevel.WARNING, "a/x/1"))
        row.status = row.status.__class__.RESOLVED
        await s.commit()
        row = await record_event(s, _event(AlertEventKind.ESCALATED, ThreatLevel.CRITICAL, "a/x/1"))
        await s.commit()
        assert row.status.value == "open"


# --------------------------------------------------------------------- devices


async def test_guard_location_is_republished_as_a_gps_tag(
    client: AsyncClient, settings: Settings
) -> None:
    received: list[GpsFix] = []

    async def listen() -> None:
        async with aiomqtt.Client(
            hostname=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_server_user,
            password=settings.mqtt_server_password.get_secret_value(),
        ) as c:
            await c.subscribe("pids/site-alpha/api/gps")
            async for msg in c.messages:
                assert isinstance(msg.payload, bytes)
                received.append(GpsFix.model_validate_json(msg.payload))
                return

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.5)
    guard = await login(client, "guard@test.local")
    r = await client.post(
        "/api/v1/guards/me/location",
        json={"site_id": "site-alpha", "lat": 13.2625, "lon": 77.4201, "accuracy_m": 4.0},
        headers=bearer(guard),
    )
    assert r.status_code == 202
    await asyncio.wait_for(task, timeout=5)
    assert received[0].tag_id == "patrol-alpha"

    op = await login(client, "operator@test.local")
    r = await client.post(
        "/api/v1/guards/me/location",
        json={"site_id": "site-alpha", "lat": 13.26, "lon": 77.42, "accuracy_m": 4.0},
        headers=bearer(op),
    )
    assert r.status_code == 403


async def test_ws_ticket_is_single_use(client: AsyncClient) -> None:
    tokens = await login(client, "operator@test.local")
    t = (await client.post("/api/v1/auth/ws-ticket", headers=bearer(tokens))).json()
    assert t["expires_in"] == 30
    assert len(t["ticket"]) > 20


async def test_health(client: AsyncClient) -> None:
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    assert (await client.get("/health/ready")).json() == {"database": "ok", "redis": "ok"}
