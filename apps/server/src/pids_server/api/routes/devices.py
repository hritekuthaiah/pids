"""Guard devices: push-token registration and the phone-as-cooperative-tag GPS feed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert

from pids_core import badges
from pids_core.contracts import GeoPoint, GpsFix
from pids_server import bus
from pids_server.api.deps import AnyUser, Guard, RedisDep, SessionDep, SettingsDep, audit
from pids_server.db import models as m

router = APIRouter(tags=["devices"])


class PushTokenIn(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=255)]
    platform: Literal["android", "ios", "web"] = "android"


class BadgeOut(BaseModel):
    """What a guard's phone needs to advertise its rolling BLE badge (ADR-0012)."""

    tag_id: str
    secret_hex: str
    window_s: int
    company_id: int
    payload_prefix_hex: str = Field(description="magic + version, before the 8-byte rolling id")


class CameraIn(BaseModel):
    """A guard's phone offering its camera to the site (ADR-0013)."""

    site_id: str
    url: Annotated[str, Field(pattern=r"^https?://[^\s]{3,200}$")]
    width: Annotated[int, Field(gt=0, le=8000)]
    height: Annotated[int, Field(gt=0, le=8000)]
    fps: Annotated[float, Field(gt=0, le=60)]


class CameraOut(BaseModel):
    name: str
    url: str
    width: int
    height: int
    fps: float
    seen_at: datetime


class LocationIn(BaseModel):
    site_id: str
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    accuracy_m: Annotated[float, Field(ge=0, le=500)]
    at: datetime | None = None


@router.post("/devices/push-token", status_code=status.HTTP_204_NO_CONTENT)
async def register_push_token(body: PushTokenIn, principal: AnyUser, session: SessionDep) -> None:
    stmt = insert(m.PushToken).values(
        token=body.token, user_id=principal.user_id, platform=body.platform
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[m.PushToken.token],
            set_={"user_id": principal.user_id, "platform": body.platform},
        )
    )
    await session.commit()


#: A phone drops off the list this long after it stops announcing itself.
CAMERA_TTL_S = 90


@router.post("/devices/camera", status_code=status.HTTP_204_NO_CONTENT)
async def register_camera(body: CameraIn, principal: Guard, redis: RedisDep) -> None:
    """A guard's phone says where its stream can be reached, so an operator can read it
    off the console instead of hunting for the phone's IP. Video never passes through
    the server: the edge node pulls it directly over the local network."""
    entry = {
        "name": principal.name,
        "url": body.url,
        "width": body.width,
        "height": body.height,
        "fps": body.fps,
        "seen_at": datetime.now(UTC).isoformat(),
    }
    await redis.set(
        bus.camera_key(body.site_id, str(principal.user_id)),
        json.dumps(entry),
        ex=CAMERA_TTL_S,
    )


@router.get("/sites/{site_id}/cameras", response_model=list[CameraOut])
async def list_cameras(site_id: str, _: AnyUser, redis: RedisDep) -> list[CameraOut]:
    """Phone cameras currently offering themselves to this site."""
    out: list[CameraOut] = []
    async for key in redis.scan_iter(match=bus.camera_key(site_id, "*"), count=50):
        raw = await redis.get(key)
        if raw:
            out.append(CameraOut.model_validate(json.loads(raw)))
    return sorted(out, key=lambda c: c.name)


@router.get("/guards/me/badge", response_model=BadgeOut)
async def my_badge(
    principal: Guard, settings: SettingsDep, session: SessionDep, request: Request
) -> BadgeOut:
    """The calling guard's badge secret — only their own, only over an authenticated
    session. Phones derive the rolling identifier locally; nothing else is shared."""
    if principal.tag_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no tag is assigned to this guard")
    if settings.badge_key is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "BLE badges are not configured")
    raw = settings.badge_key.get_secret_value()
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = raw.encode()
    await audit(session, principal, "badge.issue", principal.tag_id, request)
    await session.commit()
    return BadgeOut(
        tag_id=principal.tag_id,
        secret_hex=badges.badge_secret(key, principal.tag_id).hex(),
        window_s=badges.WINDOW_S,
        company_id=badges.COMPANY_ID,
        payload_prefix_hex=(badges.MAGIC + bytes([badges.VERSION_ROLLING])).hex(),
    )


@router.post("/guards/me/location", status_code=status.HTTP_202_ACCEPTED)
async def report_location(body: LocationIn, principal: Guard, request: Request) -> dict[str, str]:
    """A guard's phone reports its position; it enters the decision engine as a
    cooperative GPS tag, exactly like a hardware tag would."""
    if principal.tag_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no tag is assigned to this guard")
    now = datetime.now(UTC)
    fix = GpsFix(
        site_id=body.site_id,
        tag_id=principal.tag_id,
        at=body.at or now,
        position=GeoPoint(lat=body.lat, lon=body.lon),
        accuracy_m=body.accuracy_m,
        trace={"captured": body.at or now, "api": now},
    )
    await request.app.state.mqtt.publish(
        bus.mqtt_publish(body.site_id, bus.API_NODE, "gps"), bus.dumps(fix), qos=1
    )
    return {"status": "accepted", "tag_id": principal.tag_id}
