"""API integration tests against real Postgres/PostGIS, Redis and MQTT."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

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
from pids_core.site import SiteConfig
from pids_server.db.session import Database
from pids_server.decision.recorder import record_event
from pids_server.settings import Settings
from pids_server.site_store import active_site_id, upsert_site
from server_helpers import PASSWORD, bearer, login

pytestmark = pytest.mark.integration

DEMO_ROOM = Path(__file__).resolve().parents[3] / "config/sites/demo-room.yaml"


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


async def test_the_live_site_is_listed_first(
    client: AsyncClient, db: Database, settings: Settings
) -> None:
    async with db.session() as s:
        await upsert_site(s, SiteConfig.from_yaml(DEMO_ROOM))
        await s.commit()
    tokens = await login(client, "operator@test.local")
    ids = [x["id"] for x in (await client.get("/api/v1/sites", headers=bearer(tokens))).json()]
    live = active_site_id(settings.site_config)
    assert sorted(ids) == ["demo-room", "site-alpha"]
    assert ids[0] == live  # the console opens on the site with a decision service


async def test_a_guard_gets_only_their_own_badge_secret(
    client: AsyncClient, settings: Settings
) -> None:
    from pids_core.badges import BadgeResolver, rolling_id, window_of

    if settings.badge_key is None:
        pytest.skip("PIDS_BADGE_KEY not configured")
    guard = await login(client, "guard@test.local")
    r = await client.get("/api/v1/guards/me/badge", headers=bearer(guard))
    assert r.status_code == 200
    body = r.json()
    assert body["tag_id"] == "patrol-alpha"
    assert body["window_s"] == 30
    # what the phone would advertise resolves, on the scanner side, to this guard's tag
    raw = settings.badge_key.get_secret_value()
    key = bytes.fromhex(raw)
    now = datetime.now(UTC).timestamp()
    rid = rolling_id(bytes.fromhex(body["secret_hex"]), window_of(now))
    assert (
        BadgeResolver(key, ["patrol-alpha", "patrol-bravo"]).resolve(1, rid, now) == "patrol-alpha"
    )
    op = await login(client, "operator@test.local")
    assert (await client.get("/api/v1/guards/me/badge", headers=bearer(op))).status_code == 403


def _square(lon: float, lat: float, size: float = 0.0004) -> list[list[float]]:
    return [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size]]


def _zone(zid: str, kind: str, lon: float, lat: float, size: float = 0.0004) -> dict[str, object]:
    return {"id": zid, "name": zid.title(), "kind": kind, "ring": _square(lon, lat, size)}


#: site-alpha's crate-07 tag calls the armoury home, so every valid edit keeps one.
ARMOURY = _zone("armoury", "containment", 77.4208, 13.2608, 0.0002)


async def test_an_admin_redraws_the_zones_and_the_site_follows(client: AsyncClient) -> None:
    admin = await login(client, "admin@test.local")
    ring = _square(77.4205, 13.2605)
    body = {
        "zones": [
            {"id": "secure-core", "name": "Secure Core", "kind": "critical", "ring": ring},
            _zone("approach", "warning", 77.4195, 13.2595, 0.0012),
            ARMOURY,
        ]
    }
    r = await client.put("/api/v1/sites/site-alpha/geometry", json=body, headers=bearer(admin))
    assert r.status_code == 200, r.text
    site = r.json()
    assert [z["id"] for z in site["zones"]] == ["secure-core", "approach", "armoury"]

    # the drawn ring comes back where it was drawn (centimetres), closed
    drawn = next(f for f in site["geojson"]["features"] if f.get("id") == "secure-core")[
        "geometry"
    ]["coordinates"][0]
    assert drawn[0] == drawn[-1]
    for (lon, lat), (got_lon, got_lat) in zip(ring, drawn, strict=False):
        assert abs(got_lon - lon) < 1e-5
        assert abs(got_lat - lat) < 1e-5

    # and the zone rows PostGIS answers spatial queries from were rewritten too
    listed = (await client.get("/api/v1/sites", headers=bearer(admin))).json()
    assert any(s["id"] == "site-alpha" for s in listed)


async def test_moving_the_origin_keeps_the_cameras_on_the_ground(client: AsyncClient) -> None:
    admin = await login(client, "admin@test.local")
    before = (await client.get("/api/v1/sites/site-alpha", headers=bearer(admin))).json()
    node_before = next(f for f in before["geojson"]["features"] if f.get("id") == "node:edge-01")

    body = {
        "origin": {"lat": 13.2000, "lon": 77.5000},
        "zones": [_zone("secure-core", "critical", 77.4205, 13.2605), ARMOURY],
    }
    r = await client.put("/api/v1/sites/site-alpha/geometry", json=body, headers=bearer(admin))
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["center"] == [77.5, 13.2]
    node_after = next(f for f in after["geojson"]["features"] if f.get("id") == "node:edge-01")
    lon_b, lat_b = node_before["geometry"]["coordinates"]
    lon_a, lat_a = node_after["geometry"]["coordinates"]
    assert abs(lon_a - lon_b) < 1e-6
    assert abs(lat_a - lat_b) < 1e-6


async def test_the_last_critical_zone_cannot_be_deleted(client: AsyncClient) -> None:
    admin = await login(client, "admin@test.local")
    body = {"zones": [_zone("approach", "warning", 77.4195, 13.2595, 0.001), ARMOURY]}
    r = await client.put("/api/v1/sites/site-alpha/geometry", json=body, headers=bearer(admin))
    assert r.status_code == 422
    assert "critical zone" in r.json()["detail"]


async def test_a_containment_zone_an_asset_calls_home_cannot_vanish(client: AsyncClient) -> None:
    admin = await login(client, "admin@test.local")
    body = {"zones": [_zone("secure-core", "critical", 77.4205, 13.2605)]}
    r = await client.put("/api/v1/sites/site-alpha/geometry", json=body, headers=bearer(admin))
    assert r.status_code == 422
    assert "home_zone" in r.json()["detail"]


async def test_operators_cannot_redraw_zones(client: AsyncClient) -> None:
    op = await login(client, "operator@test.local")
    body = {"zones": [_zone("secure-core", "critical", 77.4205, 13.2605), ARMOURY]}
    r = await client.put("/api/v1/sites/site-alpha/geometry", json=body, headers=bearer(op))
    assert r.status_code == 403


async def test_a_phone_offers_its_camera_and_the_console_sees_it(client: AsyncClient) -> None:
    guard = await login(client, "guard@test.local")
    body = {
        "site_id": "site-alpha",
        "url": "http://192.168.0.105:8081/stream.mjpg",
        "width": 1280,
        "height": 720,
        "fps": 15,
    }
    assert (
        await client.post("/api/v1/devices/camera", json=body, headers=bearer(guard))
    ).status_code == 204

    op = await login(client, "operator@test.local")
    listed = (await client.get("/api/v1/sites/site-alpha/cameras", headers=bearer(op))).json()
    assert [c["url"] for c in listed] == [body["url"]]
    assert listed[0]["width"] == 1280

    # another site's console does not see it
    assert (await client.get("/api/v1/sites/demo-room/cameras", headers=bearer(op))).json() == []


async def test_a_camera_url_must_be_a_plain_stream_address(client: AsyncClient) -> None:
    guard = await login(client, "guard@test.local")
    for url in ("file:///etc/passwd", "javascript:alert(1)", "http://" + "x" * 300):
        body = {"site_id": "site-alpha", "url": url, "width": 640, "height": 480, "fps": 10}
        r = await client.post("/api/v1/devices/camera", json=body, headers=bearer(guard))
        assert r.status_code == 422, url


async def test_operators_do_not_register_cameras(client: AsyncClient) -> None:
    op = await login(client, "operator@test.local")
    body = {
        "site_id": "site-alpha",
        "url": "http://192.168.0.9:8081/stream.mjpg",
        "width": 640,
        "height": 480,
        "fps": 10,
    }
    assert (
        await client.post("/api/v1/devices/camera", json=body, headers=bearer(op))
    ).status_code == 403


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
