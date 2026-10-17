"""Site geometry for maps, the live snapshot, and the tag registry."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from pids_core.contracts import NodeView, ZoneKind
from pids_core.coverage import sector
from pids_core.geo import Enu, LocalFrame
from pids_core.site import Site as CoreSite
from pids_core.site import SiteConfig
from pids_server import bus
from pids_server.api.deps import Admin, AnyUser, RedisDep, SessionDep, SettingsDep, audit
from pids_server.db import models as m
from pids_server.schemas import LiveMessage, SiteChangedMessage
from pids_server.site_store import active_site_id, load_site_config, upsert_site

router = APIRouter(prefix="/sites", tags=["sites"])


class SiteSummary(BaseModel):
    id: str
    name: str


class TagOut(BaseModel):
    id: str
    label: str
    kind: str
    authorized: bool
    home_zone: str | None


class TagPatch(BaseModel):
    authorized: bool


class OriginIn(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]


class ZoneIn(BaseModel):
    """A zone as the operator drew it: a WGS84 ring of ``[lon, lat]`` vertices."""

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    kind: ZoneKind
    ring: Annotated[list[tuple[float, float]], Field(min_length=3, max_length=500)]
    actions: dict[str, list[str]] = Field(default_factory=dict)


class GeometryIn(BaseModel):
    """Zones exactly as they should be after the edit; anything omitted is deleted.

    ``origin`` moves the site's local frame. Zones arrive in WGS84 either way, so they
    stay on the ground. By default everything else in the site file is converted to the
    new frame so it too stays on the same ground (a re-frame). With ``relocate`` the
    whole site is being moved instead — nodes, readers and features keep their local
    metres and travel with the zones, which is what putting a placeholder site on its
    real location needs.
    """

    origin: OriginIn | None = None
    relocate: bool = False
    zones: Annotated[list[ZoneIn], Field(min_length=1, max_length=64)]


def _to_local(frame: LocalFrame, ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """WGS84 ``[lon, lat]`` ring -> local metres, with any repeated closing vertex dropped."""
    pts = [frame.to_enu(lat, lon) for lon, lat in ring]
    if len(pts) > 3 and pts[0].distance_to(pts[-1]) < 0.01:
        pts = pts[:-1]
    return [(round(p.east, 3), round(p.north, 3)) for p in pts]


def _remap(old: LocalFrame, new: LocalFrame, pts: list[tuple[float, float]]) -> list[list[float]]:
    """Local metres in one frame -> the same ground positions in another."""
    out = []
    for e, n in pts:
        lat, lon = old.to_wgs84(Enu(e, n))
        p = new.to_enu(lat, lon)
        out.append([round(p.east, 3), round(p.north, 3)])
    return out


def _ring(site: CoreSite, pts: list[tuple[float, float]], close: bool) -> list[list[float]]:
    """Local metres -> GeoJSON [lon, lat] coordinates."""
    out = [
        [round(lon, 7), round(lat, 7)]
        for lat, lon in (site.frame.to_wgs84(Enu(e, n)) for e, n in pts)
    ]
    if close and out and out[0] != out[-1]:
        out.append(out[0])
    return out


def _feature(fid: str, props: dict[str, Any], geom_type: str, coords: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": fid,
        "properties": props,
        "geometry": {"type": geom_type, "coordinates": coords},
    }


def site_geojson(cfg: SiteConfig) -> dict[str, Any]:
    site = CoreSite(cfg)
    features = [
        _feature(
            z.id,
            {"layer": "zone", "id": z.id, "name": z.name, "kind": z.kind.value},
            "Polygon",
            [_ring(site, z.polygon, True)],
        )
        for z in cfg.zones
    ]
    for n in cfg.nodes:
        cov = sector(n.position, n.heading_deg, n.fov_deg, n.range_m)
        pts = [(float(x), float(y)) for x, y in cov.exterior.coords]
        features += [
            _feature(
                f"coverage:{n.id}",
                {"layer": "coverage", "id": n.id, "thermal": n.thermal is not None},
                "Polygon",
                [_ring(site, pts, True)],
            ),
            _feature(
                f"node:{n.id}",
                {"layer": "node", "id": n.id, "heading": n.heading_deg},
                "Point",
                _ring(site, [n.position], False)[0],
            ),
        ]
    features += [
        _feature(
            f"reader:{r.id}",
            {"layer": "reader", "id": r.id},
            "Point",
            _ring(site, [r.position], False)[0],
        )
        for r in cfg.readers
    ]
    features += [
        _feature(f"road:{k}", {"layer": "road", "id": k}, "LineString", _ring(site, v, False))
        for k, v in cfg.features.roads.items()
    ]
    features += [
        _feature(
            f"route:{k}", {"layer": "patrol_route", "id": k}, "LineString", _ring(site, v, False)
        )
        for k, v in cfg.features.patrol_routes.items()
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("", response_model=list[SiteSummary])
async def list_sites(_: AnyUser, session: SessionDep, settings: SettingsDep) -> list[SiteSummary]:
    """All seeded sites, the live one (``PIDS_SITE_CONFIG``) first."""
    live = active_site_id(settings.site_config)
    rows = (await session.scalars(select(m.Site).order_by(m.Site.id))).all()
    rows = sorted(rows, key=lambda r: r.id != live)
    return [SiteSummary(id=r.id, name=r.name) for r in rows]


@router.get("/{site_id}")
async def get_site(site_id: str, _: AnyUser, session: SessionDep) -> dict[str, Any]:
    """Everything a map needs, as GeoJSON in WGS84."""
    try:
        cfg = await load_site_config(session, site_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {
        "id": cfg.site.id,
        "name": cfg.site.name,
        "timezone": cfg.site.timezone,
        "center": [cfg.site.origin.lon, cfg.site.origin.lat],
        "zones": [
            {"id": z.id, "name": z.name, "kind": z.kind.value, "actions": z.actions}
            for z in cfg.zones
        ],
        "geojson": site_geojson(cfg),
    }


@router.get(
    "/{site_id}/live",
    response_class=Response,
    responses={
        200: {"model": LiveMessage, "description": "Latest live snapshot (also pushed over /ws)"},
        204: {"description": "No snapshot yet"},
    },
)
async def live(site_id: str, _: AnyUser, redis: RedisDep) -> Response:
    raw = await redis.get(bus.live_key(site_id))
    if raw is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Response(content=raw, media_type="application/json")


@router.get("/{site_id}/views", response_model=list[NodeView])
async def list_views(site_id: str, _: AnyUser, redis: RedisDep) -> list[NodeView]:
    """Where each camera is actually looking: its ground footprint and pixel mapping.

    Published by the edge nodes after calibration, so the console draws the real
    visible area instead of an idealised sector, and can turn a point in a camera
    image into a point on the map.
    """
    out: list[NodeView] = []
    async for key in redis.scan_iter(match=bus.view_key(site_id, "*"), count=50):
        raw = await redis.get(key)
        if raw:
            out.append(NodeView.model_validate_json(raw))
    return sorted(out, key=lambda v: v.node_id)


@router.put("/{site_id}/geometry")
async def put_geometry(
    site_id: str,
    body: GeometryIn,
    principal: Admin,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
) -> dict[str, Any]:
    """Replace a site's zones (and optionally move its origin), live.

    The decision engine picks the new geometry up without a restart, and every open
    console is told to refetch. Deleting the last critical zone, or a containment zone
    an asset tag still calls home, is refused: those are what CRITICAL means.
    """
    try:
        cfg = await load_site_config(session, site_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    old = LocalFrame(cfg.site.origin.lat, cfg.site.origin.lon)
    origin = body.origin or OriginIn(lat=cfg.site.origin.lat, lon=cfg.site.origin.lon)
    new = LocalFrame(origin.lat, origin.lon)
    moved = (origin.lat, origin.lon) != (cfg.site.origin.lat, cfg.site.origin.lon)

    raw: dict[str, Any] = cfg.model_dump(mode="json")
    kept = {z["id"]: z["actions"] for z in raw["zones"]}
    raw["site"]["origin"] = {"lat": origin.lat, "lon": origin.lon}
    raw["zones"] = [
        {
            "id": z.id,
            "name": z.name,
            "kind": z.kind.value,
            "polygon": _to_local(new, z.ring),
            # the console has no editor for notification actions, so a zone it re-sends
            # bare keeps the ones the site file gave it
            "actions": z.actions or kept.get(z.id, {}),
        }
        for z in body.zones
    ]
    if moved and not body.relocate:  # keep nodes, readers and features on the same ground
        for node in raw["nodes"]:
            node["position"] = _remap(old, new, [node["position"]])[0]
        for reader in raw["readers"]:
            reader["position"] = _remap(old, new, [reader["position"]])[0]
        feats = raw["features"]
        for group in ("roads", "patrol_routes"):
            feats[group] = {k: _remap(old, new, v) for k, v in feats[group].items()}
        feats["gates"] = {k: _remap(old, new, [v])[0] for k, v in feats["gates"].items()}
    try:
        updated = SiteConfig.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _first_error(exc)) from exc

    await upsert_site(session, updated)
    await audit(
        session,
        principal,
        "site.geometry",
        site_id,
        request,
        zones=[z.id for z in body.zones],
        origin_moved=moved,
        relocated=moved and body.relocate,
    )
    await session.commit()
    await redis.publish(bus.config_channel(site_id), b"geometry")
    await redis.publish(
        bus.site_channel(site_id),
        bus.dumps(SiteChangedMessage(site_id=site_id, at=datetime.now(UTC))),
    )
    return await get_site(site_id, principal, session)


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    return str(err.get("msg", "invalid site geometry")).removeprefix("Value error, ")


@router.get("/{site_id}/tags", response_model=list[TagOut])
async def list_tags(site_id: str, _: AnyUser, session: SessionDep) -> list[TagOut]:
    rows = (
        await session.scalars(select(m.Tag).where(m.Tag.site_id == site_id).order_by(m.Tag.id))
    ).all()
    return [
        TagOut(id=t.id, label=t.label, kind=t.kind, authorized=t.authorized, home_zone=t.home_zone)
        for t in rows
    ]


@router.patch("/{site_id}/tags/{tag_id}", response_model=TagOut)
async def patch_tag(
    site_id: str,
    tag_id: str,
    body: TagPatch,
    principal: Admin,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
) -> TagOut:
    """Authorise or revoke a tag. Takes effect in the decision engine immediately."""
    tag = await session.get(m.Tag, (site_id, tag_id))
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tag not found")
    tag.authorized = body.authorized
    await audit(
        session, principal, "tag.update", f"{site_id}/{tag_id}", request, authorized=body.authorized
    )
    await session.commit()
    await redis.publish(bus.config_channel(site_id), b"tags")
    return TagOut(
        id=tag.id,
        label=tag.label,
        kind=tag.kind,
        authorized=tag.authorized,
        home_zone=tag.home_zone,
    )
