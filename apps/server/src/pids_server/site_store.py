"""Site persistence: seed PostGIS from a site file and load it back for the engine.

The full ``SiteConfig`` (local metres) is stored on the site row so the decision
engine reconstructs exactly what the simulator and evaluation use; zones and tags
are also materialised as rows — zones as WGS84 polygons with a GiST index for
spatial queries, tags for administration (revocation takes effect immediately).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point, Polygon
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pids_core.geo import Enu
from pids_core.site import Site as CoreSite
from pids_core.site import SiteConfig, TagConfig
from pids_server.db import models as m


def zone_polygon_wgs84(site: CoreSite, points: list[tuple[float, float]]) -> Polygon:
    ring = []
    for e, n in points:
        lat, lon = site.frame.to_wgs84(Enu(e, n))
        ring.append((lon, lat))
    return Polygon(ring)


async def upsert_site(session: AsyncSession, cfg: SiteConfig) -> None:
    site = CoreSite(cfg)
    info = cfg.site
    row = await session.get(m.Site, info.id)
    payload: dict[str, Any] = cfg.model_dump(mode="json")
    origin = from_shape(Point(info.origin.lon, info.origin.lat), srid=4326)
    if row is None:
        session.add(
            m.Site(
                id=info.id, name=info.name, timezone=info.timezone, origin=origin, config=payload
            )
        )
    else:
        row.name, row.timezone, row.origin, row.config = info.name, info.timezone, origin, payload

    await session.execute(delete(m.Zone).where(m.Zone.site_id == info.id))
    for z in cfg.zones:
        session.add(
            m.Zone(
                site_id=info.id,
                id=z.id,
                name=z.name,
                kind=z.kind.value,
                geom=from_shape(zone_polygon_wgs84(site, z.polygon), srid=4326),
                actions={k.value: v for k, v in z.actions.items()},
            )
        )
    existing = {
        t.id: t
        for t in (await session.scalars(select(m.Tag).where(m.Tag.site_id == info.id))).all()
    }
    for t in cfg.tags:
        row_t = existing.get(t.id)
        if row_t is None:
            session.add(
                m.Tag(
                    site_id=info.id,
                    id=t.id,
                    label=t.label,
                    kind=t.kind.value,
                    authorized=t.authorized,
                    home_zone=t.home_zone,
                )
            )
        else:
            row_t.label, row_t.kind, row_t.home_zone = t.label, t.kind.value, t.home_zone


async def load_site_config(session: AsyncSession, site_id: str) -> SiteConfig:
    """The stored SiteConfig, with tag rows (the live registry) overriding the file."""
    row = await session.get(m.Site, site_id)
    if row is None:
        raise LookupError(f"site {site_id!r} is not seeded; run `pids-admin seed`")
    cfg = SiteConfig.model_validate(row.config)
    tags = (await session.scalars(select(m.Tag).where(m.Tag.site_id == site_id))).all()
    return cfg.model_copy(
        update={
            "tags": [
                TagConfig.model_validate(
                    {
                        "id": t.id,
                        "label": t.label,
                        "kind": t.kind,
                        "authorized": t.authorized,
                        "home_zone": t.home_zone,
                    }
                )
                for t in tags
            ]
        }
    )


async def site_ids(session: AsyncSession) -> list[str]:
    return list((await session.scalars(select(m.Site.id))).all())


@cache
def active_site_id(site_file: Path) -> str | None:
    """The site this deployment runs live: the one ``PIDS_SITE_CONFIG`` names.

    Other seeded sites stay browsable, but only this one has a decision service.
    """
    try:
        return SiteConfig.from_yaml(site_file).site.id
    except FileNotFoundError:
        return None
