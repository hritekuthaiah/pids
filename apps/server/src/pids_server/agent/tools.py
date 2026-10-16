"""The agent's read-only tools: what it may look at, never what it may change.

Every tool returns compact JSON text. Results are data from the system's own records
(and, for tag labels, from administrators); the system prompt tells the model to treat
them as data, never as instructions.
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pids_server.agent import procedures
from pids_server.agent.llm import ToolSpec
from pids_server.db import models as m
from pids_server.site_store import load_site_config


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


TOOLS: list[ToolSpec] = [
    ToolSpec(
        "get_alert",
        "The alert under review: level, zone, entity, reason, its event history and the "
        "per-channel evidence (log-odds contributions) behind the threat score.",
        _obj({"alert_id": {"type": "string"}}),
    ),
    ToolSpec(
        "recent_alerts",
        "Other alerts at this site opened in the last N minutes (1-1440), newest first — "
        "use to spot coordinated probes or repeat visitors.",
        _obj({"minutes": {"type": "integer"}}),
    ),
    ToolSpec(
        "entity_history",
        "What one tracked entity did over the last N minutes (1-60): zones visited in order, "
        "highest level, distance travelled and average speed.",
        _obj({"entity_id": {"type": "string"}, "minutes": {"type": "integer"}}),
    ),
    ToolSpec(
        "site_overview",
        "The protected site: its zones (warning / critical / containment) and the registered "
        "cooperative tags with whether each is currently authorised.",
        _obj({}),
    ),
    ToolSpec(
        "search_procedures",
        "Search the site's standard operating procedures. Returns sections with ids like "
        "'sop-01-intrusion-response#1'; cite those ids for any recommended action.",
        _obj({"query": {"type": "string"}}),
    ),
]


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((b[0] - a[0]) * 111_195.0, (b[1] - a[1]) * 111_195.0 * math.cos(lat))


class ToolBox:
    """Executes tool calls for one site against the database (read-only session)."""

    def __init__(self, session: AsyncSession, site_id: str) -> None:
        self.session = session
        self.site_id = site_id
        #: procedure section ids actually returned to the model (citations are checked against it)
        self.retrieved: set[str] = set()

    async def __call__(self, name: str, args: dict[str, Any]) -> str:
        handler = getattr(self, f"_{name}", None)
        if handler is None or name not in {t.name for t in TOOLS}:
            raise ValueError(f"unknown tool {name!r}")
        return json.dumps(await handler(**args), default=str)

    async def _get_alert(self, alert_id: str) -> dict[str, Any]:
        row = await self.session.get(m.Alert, alert_id)
        if row is None or row.site_id != self.site_id:
            return {"error": f"no alert {alert_id} at this site"}
        a = row.last_assessment
        return {
            "id": row.id,
            "status": row.status.value,
            "level": row.level,
            "max_level": row.max_level,
            "score": row.score,
            "zone_id": row.zone_id,
            "entity_id": row.entity_id,
            "entity_class": row.entity_class,
            "tag_id": row.tag_id,
            "authorized": a.get("authorized"),
            "reason": row.reason,
            "opened_at": row.opened_at,
            "track_lost": row.track_lost,
            "flags": a.get("flags", []),
            "time_to_breach_s": a.get("time_to_breach_s"),
            "sources": a.get("sources", []),
            "evidence_log_odds": {
                c["channel"]: round(float(c["log_odds"]), 2)
                for c in a.get("contributions", [])
                if abs(float(c.get("log_odds", 0))) >= 0.05
            },
            "events": [
                {"kind": e.kind, "level": e.level, "at": e.at, "reason": e.reason}
                for e in row.events
            ][-12:],
        }

    async def _recent_alerts(self, minutes: int) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(minutes=max(1, min(minutes, 1440)))
        rows = (
            await self.session.scalars(
                select(m.Alert)
                .where(m.Alert.site_id == self.site_id, m.Alert.opened_at >= since)
                .order_by(m.Alert.opened_at.desc())
                .limit(20)
            )
        ).all()
        return {
            "alerts": [
                {
                    "id": r.id,
                    "level": r.max_level,
                    "zone_id": r.zone_id,
                    "entity_class": r.entity_class,
                    "status": r.status.value,
                    "opened_at": r.opened_at,
                    "reason": r.reason,
                }
                for r in rows
            ]
        }

    async def _entity_history(self, entity_id: str, minutes: int) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(minutes=max(1, min(minutes, 60)))
        rows = (
            await self.session.scalars(
                select(m.Observation)
                .where(
                    m.Observation.site_id == self.site_id,
                    m.Observation.entity_id == entity_id,
                    m.Observation.at >= since,
                )
                .order_by(m.Observation.at)
            )
        ).all()
        if not rows:
            return {"entity_id": entity_id, "samples": 0}
        pts = [(p.y, p.x) for p in (to_shape(r.position) for r in rows)]
        dist = sum(_dist_m(a, b) for a, b in itertools.pairwise(pts))
        span = (rows[-1].at - rows[0].at).total_seconds()
        zones: list[str] = []
        for r in rows:
            z = r.zone_id or "outside"
            if not zones or zones[-1] != z:
                zones.append(z)
        levels = ["nominal", "elevated", "warning", "critical"]
        return {
            "entity_id": entity_id,
            "samples": len(rows),
            "first_seen": rows[0].at,
            "last_seen": rows[-1].at,
            "zones_in_order": zones,
            "highest_level": max(
                (r.level for r in rows), key=lambda lv: levels.index(lv) if lv in levels else 0
            ),
            "distance_m": round(dist, 1),
            "mean_speed_mps": round(dist / span, 2) if span > 0 else 0.0,
            "tag_id": rows[-1].tag_id,
        }

    async def _site_overview(self) -> dict[str, Any]:
        cfg = await load_site_config(self.session, self.site_id)
        return {
            "site": cfg.site.name,
            "zones": [{"id": z.id, "name": z.name, "kind": z.kind.value} for z in cfg.zones],
            "cameras": len(cfg.nodes),
            "tags": [
                {"id": t.id, "label": t.label, "kind": t.kind.value, "authorized": t.authorized}
                for t in cfg.tags
            ],
        }

    async def _search_procedures(self, query: str) -> dict[str, Any]:
        sections = await procedures.search(self.session, query, k=4)
        self.retrieved.update(str(s["id"]) for s in sections)
        return {"sections": sections}
