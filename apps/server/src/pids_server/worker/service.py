"""``pids-worker`` — durable notification dispatch.

Consumes alert jobs from a Redis Stream with a consumer group: each job is
acknowledged only after dispatch is recorded, and jobs left pending by a crashed
worker are reclaimed after ``RECLAIM_IDLE_MS``. Channels are chosen per zone and
level from the site configuration (``zones[].actions``).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import Any

import httpx
from prometheus_client import start_http_server
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import select

from pids_core.site import SiteConfig
from pids_server import bus, metrics
from pids_server.db import models as m
from pids_server.db.session import Database
from pids_server.logs import configure, log
from pids_server.schemas import AlertOut
from pids_server.settings import Settings, get_settings
from pids_server.site_store import load_site_config, site_ids
from pids_server.worker.channels import Channel, ExpoPush, RecordedMessage, Siren

RECLAIM_IDLE_MS = 60_000
DEFAULT_ACTIONS = {"warning": ["dashboard", "push"], "critical": ["dashboard", "push", "siren"]}


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.database_url)
        self.redis: Redis = Redis.from_url(settings.redis_url)
        self.consumer = f"worker-{os.getpid()}"
        self._stop = asyncio.Event()
        self._sites: dict[str, SiteConfig] = {}

    async def _site(self, site_id: str) -> SiteConfig:
        if site_id not in self._sites:
            async with self.db.session() as s:
                self._sites[site_id] = await load_site_config(s, site_id)
        return self._sites[site_id]

    async def _recipients(self) -> list[str]:
        async with self.db.session() as s:
            rows = await s.scalars(
                select(m.PushToken.token)
                .join(m.User, m.User.id == m.PushToken.user_id)
                .where(m.User.active.is_(True))
            )
            return list(rows.all())

    async def handle(self, job: dict[str, str], channels: dict[str, Channel]) -> None:
        site = await self._site(job["site_id"])
        zone = next((z for z in site.zones if z.id == job.get("zone_id")), None)
        actions = (
            {k.value: v for k, v in zone.actions.items()}
            if zone and zone.actions
            else DEFAULT_ACTIONS
        )
        wanted = [c for c in actions.get(job["level"], []) if c != "dashboard"]
        async with self.db.session() as s:
            row = await s.get(m.Alert, job["alert_id"])
            if row is None:
                log.warning("job for unknown alert", alert_id=job["alert_id"])
                return
            alert = AlertOut.of(row)
            recipients = await self._recipients() if "push" in wanted else []
            for name in wanted:
                channel = channels.get(name)
                if channel is None:
                    continue
                result = await channel.send(alert, recipients if name == "push" else [])
                metrics.NOTIFICATIONS.labels(channel=name, status=result.status).inc()
                s.add(
                    m.Notification(
                        alert_id=alert.id, channel=name, status=result.status, detail=result.detail
                    )
                )
                log.info("dispatched", channel=name, status=result.status, alert_id=alert.id)
            await s.commit()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        with contextlib.suppress(ResponseError):  # group already exists
            await self.redis.xgroup_create(
                bus.NOTIFY_STREAM, bus.NOTIFY_GROUP, id="0", mkstream=True
            )
        async with self.db.session() as session:
            for site_id in await site_ids(session):
                self._sites[site_id] = await load_site_config(session, site_id)
        s = self.settings
        async with (
            httpx.AsyncClient() as http,
            bus.mqtt_client(s, f"pids-worker-{os.getpid()}") as mqtt,
        ):
            node_ids = [n.id for site in self._sites.values() for n in site.nodes] or ["edge-01"]
            channels: dict[str, Channel] = {
                "push": ExpoPush(
                    http, s.expo_access_token.get_secret_value() if s.expo_access_token else None
                ),
                "siren": Siren(mqtt, node_ids),
                "email": RecordedMessage("email"),
                "sms": RecordedMessage("sms"),
            }
            log.info("worker ready", consumer=self.consumer)
            while not self._stop.is_set():
                await self._reclaim(channels)
                resp: Any = await self.redis.xreadgroup(
                    bus.NOTIFY_GROUP, self.consumer, {bus.NOTIFY_STREAM: ">"}, count=10, block=2000
                )
                for _stream, entries in resp or []:
                    for msg_id, fields in entries:
                        await self._process(msg_id, fields, channels)
        await self.redis.aclose()
        await self.db.dispose()

    async def _process(
        self, msg_id: bytes, fields: dict[bytes, bytes], channels: dict[str, Channel]
    ) -> None:
        job = {k.decode(): v.decode() for k, v in fields.items()}
        try:
            await self.handle(job, channels)
        except Exception:
            log.exception("job failed; will be reclaimed", alert_id=job.get("alert_id"))
            return
        await self.redis.xack(bus.NOTIFY_STREAM, bus.NOTIFY_GROUP, msg_id)

    async def _reclaim(self, channels: dict[str, Channel]) -> None:
        resp: Any = await self.redis.xautoclaim(
            bus.NOTIFY_STREAM,
            bus.NOTIFY_GROUP,
            self.consumer,
            min_idle_time=RECLAIM_IDLE_MS,
            count=10,
        )
        for msg_id, fields in resp[1] if resp else []:
            if fields:
                await self._process(msg_id, fields, channels)


async def amain() -> None:
    settings = get_settings()
    configure(settings.log_level, json=settings.env == "prod")
    start_http_server(settings.metrics_port_worker)
    await Worker(settings).run()


def main() -> None:
    asyncio.run(amain())
