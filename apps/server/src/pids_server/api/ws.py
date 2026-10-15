"""WebSocket gateway.

One Redis pattern-subscription per API process feeds an in-process hub, which
fans out to every connected client of a site. Each client has a bounded queue:
live snapshots are droppable (the next one supersedes them) but alert messages
are never dropped — a slow client gets disconnected rather than silently
missing an alert, and reconnects to a fresh snapshot.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis
from sqlalchemy import select

from pids_server import bus
from pids_server.db import models as m
from pids_server.logs import log
from pids_server.schemas import AlertOut

router = APIRouter()

_QUEUE_SIZE = 64


class _Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self.overflowed = False

    def offer(self, payload: bytes, droppable: bool) -> None:
        if self.queue.full():
            if droppable:
                return
            self.overflowed = True
            return
        self.queue.put_nowait(payload)


class Hub:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.clients: dict[str, set[_Client]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump(), name="ws-hub")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _pump(self) -> None:
        while True:
            try:
                pubsub = self.redis.pubsub()
                await pubsub.psubscribe("pids:*:live", "pids:*:alerts")
                async for msg in pubsub.listen():
                    if msg.get("type") != "pmessage":
                        continue
                    channel = (
                        msg["channel"].decode()
                        if isinstance(msg["channel"], bytes)
                        else msg["channel"]
                    )
                    _, site_id, kind = channel.split(":", 2)
                    for client in list(self.clients.get(site_id, ())):
                        client.offer(msg["data"], droppable=kind == "live")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ws hub lost redis; resubscribing")
                await asyncio.sleep(1.0)

    def add(self, site_id: str, client: _Client) -> None:
        self.clients[site_id].add(client)

    def remove(self, site_id: str, client: _Client) -> None:
        self.clients[site_id].discard(client)


@router.websocket("/ws")
async def websocket(ws: WebSocket, ticket: str, site_id: str) -> None:
    redis: Redis = ws.app.state.redis
    raw = await redis.getdel(bus.ws_ticket_key(ticket))
    if raw is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid or expired ticket")
        return
    who: dict[str, Any] = bus.loads(raw)
    await ws.accept()
    hub: Hub = ws.app.state.hub
    client = _Client(ws)
    hub.add(site_id, client)
    log.info("ws connected", site=site_id, user=who["user_id"])
    try:
        await _send_initial(ws, redis, site_id)
        sender = asyncio.create_task(_sender(client))
        receiver = asyncio.create_task(_receiver(ws))
        _done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(site_id, client)
        log.info("ws disconnected", site=site_id, user=who["user_id"])


async def _send_initial(ws: WebSocket, redis: Redis, site_id: str) -> None:
    latest = await redis.get(bus.live_key(site_id))
    if latest is not None:
        await ws.send_bytes(latest if isinstance(latest, bytes) else latest.encode())
    async with ws.app.state.db.session() as session:
        rows = (
            await session.scalars(
                select(m.Alert)
                .where(
                    m.Alert.site_id == site_id,
                    m.Alert.status.in_([m.AlertStatus.OPEN, m.AlertStatus.ACKNOWLEDGED]),
                )
                .order_by(m.Alert.opened_at.desc())
                .limit(200)
            )
        ).all()
    await ws.send_bytes(
        bus.dumps({"type": "alerts_snapshot", "alerts": [AlertOut.of(r) for r in rows]})
    )


async def _sender(client: _Client) -> None:
    while True:
        payload = await client.queue.get()
        if client.overflowed:
            await client.ws.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="client too slow")
            return
        await client.ws.send_bytes(payload)


async def _receiver(ws: WebSocket) -> None:
    # Clients only send keep-alives; reading also surfaces disconnects promptly.
    while True:
        msg = await ws.receive_text()
        if msg == "ping":
            await ws.send_text("pong")
