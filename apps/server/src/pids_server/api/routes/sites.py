"""Site geometry for maps, the live snapshot, and the tag registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from pids_core.coverage import sector
from pids_core.geo import Enu
from pids_core.site import Site as CoreSite
from pids_core.site import SiteConfig
from pids_server import bus
from pids_server.api.deps import Admin, AnyUser, RedisDep, SessionDep, audit
from pids_server.db import models as m
from pids_server.site_store import load_site_config

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
async def list_sites(_: AnyUser, session: SessionDep) -> list[SiteSummary]:
    rows = (await session.scalars(select(m.Site))).all()
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


@router.get("/{site_id}/live")
async def live(site_id: str, _: AnyUser, redis: RedisDep) -> Response:
    raw = await redis.get(bus.live_key(site_id))
    if raw is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Response(content=raw, media_type="application/json")


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
