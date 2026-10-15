"""``pids-decision`` — runs the decision core on live telemetry for one site.

    MQTT (tracks / gps / sensors)  ->  DecisionEngine.ingest_*
    every 1/tick_hz seconds        ->  DecisionEngine.step(now)
        assessments  -> Redis live snapshot (throttled) + 1 Hz observations (Postgres)
        alert events -> Postgres (alerts, alert_events) -> Redis alerts channel
                        -> notification job on a durable Redis stream

The engine is synchronous and pure; everything here is I/O around it, all on one
event loop, so ingest and step never interleave mid-update.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
from datetime import UTC, datetime
from typing import Any

import aiomqtt
from prometheus_client import start_http_server
from pydantic import ValidationError
from redis.asyncio import Redis

from pids_core.contracts import (
    AlertEvent,
    AlertEventKind,
    GpsFix,
    TagRead,
    ThreatAssessment,
    TrackBatch,
)
from pids_core.engine import DecisionEngine, DecisionModel
from pids_core.site import Site
from pids_server import bus, metrics
from pids_server.db.session import Database
from pids_server.decision.recorder import record_event, record_observations
from pids_server.logs import configure, log
from pids_server.schemas import AlertMessage, AlertOut, LiveMessage
from pids_server.settings import Settings, get_settings
from pids_server.site_store import load_site_config, site_ids

_STREAMS = ("tracks", "gps", "sensors")
_TRACE_HOPS = [("captured", "received"), ("received", "decided"), ("captured", "decided")]


def _load_scorer(settings: Settings) -> Any:
    if not settings.anomaly_model.exists():
        log.warning(
            "anomaly model missing; behaviour channel disabled", path=str(settings.anomaly_model)
        )
        return None
    from pids_ml.anomaly import IsolationForestScorer

    return IsolationForestScorer.load(settings.anomaly_model)


class DecisionService:
    def __init__(self, settings: Settings, site: Site, model: DecisionModel, scorer: Any) -> None:
        self.settings = settings
        self.site = site
        self.engine = DecisionEngine(
            site, model.engine_config(), anomaly_scorer=scorer, run_id=f"{int(time.time()):x}"
        )
        self.db = Database(settings.database_url)
        self.redis: Redis = Redis.from_url(settings.redis_url)
        self._last_live = 0.0
        self._last_obs = 0.0
        self._stop = asyncio.Event()

    # ----------------------------------------------------------------- ingest

    def _ingest(self, stream: str, payload: bytes) -> None:
        received = datetime.now(UTC)
        try:
            if stream == "tracks":
                batch = TrackBatch.model_validate_json(payload)
                if batch.site_id != self.site.id:
                    return
                self.engine.ingest_tracks(
                    batch.model_copy(update={"trace": {**batch.trace, "received": received}})
                )
            elif stream == "gps":
                fix = GpsFix.model_validate_json(payload)
                if fix.site_id != self.site.id:
                    return
                self.engine.ingest_gps(
                    fix.model_copy(update={"trace": {**fix.trace, "received": received}}),
                    received_at=received,
                )
            elif stream == "sensors":
                read = TagRead.model_validate_json(payload)
                if read.site_id == self.site.id:
                    self.engine.ingest_tag_read(read)
        except ValidationError as exc:
            metrics.MESSAGES.labels(stream=stream, result="invalid").inc()
            log.warning("invalid telemetry", stream=stream, errors=exc.error_count())
            return
        metrics.MESSAGES.labels(stream=stream, result="ok").inc()

    async def mqtt_loop(self) -> None:
        s = self.settings
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=s.mqtt_host,
                    port=s.mqtt_port,
                    username=s.mqtt_server_user,
                    password=s.mqtt_server_password.get_secret_value(),
                    identifier=f"pids-decision-{self.site.id}",
                ) as client:
                    for stream in _STREAMS:
                        await client.subscribe(bus.mqtt_telemetry(self.site.id, stream), qos=1)
                    log.info("mqtt connected", site=self.site.id)
                    backoff = 1.0
                    async for message in client.messages:
                        stream = str(message.topic).rsplit("/", 1)[-1]
                        if isinstance(message.payload, bytes | bytearray):
                            self._ingest(stream, bytes(message.payload))
            except aiomqtt.MqttError as exc:
                log.warning("mqtt disconnected; retrying", error=str(exc), in_s=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    # ------------------------------------------------------------------- step

    async def tick_loop(self) -> None:
        period = 1.0 / self.settings.decision_tick_hz
        while not self._stop.is_set():
            started = time.perf_counter()
            now = datetime.now(UTC)
            with metrics.STEP_SECONDS.time():
                result = self.engine.step(now)
            metrics.ENTITIES.labels(site=self.site.id).set(len(result.assessments))
            for a in result.assessments:
                metrics.observe_trace(a.trace, _TRACE_HOPS)
            try:
                await self._handle_events(result.events)
                await self._publish_live(now, result.assessments)
                await self._observe(result.assessments)
            except Exception:  # keep deciding even if a sink is briefly down
                log.exception("output sink failed")
            await asyncio.sleep(max(0.0, period - (time.perf_counter() - started)))

    async def _handle_events(self, events: list[AlertEvent]) -> None:
        for ev in events:
            metrics.ALERT_EVENTS.labels(kind=ev.kind.value, level=ev.level.value).inc()
            async with self.db.session() as session:
                row = await record_event(session, ev)
                await session.commit()
                out = AlertOut.of(row)
            await self.redis.publish(
                bus.alerts_channel(self.site.id),
                bus.dumps(AlertMessage(event=ev.kind.value, alert=out)),
            )
            if ev.kind in (AlertEventKind.RAISED, AlertEventKind.ESCALATED):
                await self.redis.xadd(
                    bus.NOTIFY_STREAM,
                    {
                        "alert_id": ev.alert_id,
                        "site_id": self.site.id,
                        "kind": ev.kind.value,
                        "level": ev.level.value,
                        "zone_id": ev.assessment.zone_id or "",
                    },
                    maxlen=10_000,
                    approximate=True,
                )
            log.info(
                "alert",
                kind=ev.kind.value,
                level=ev.level.value,
                alert_id=ev.alert_id,
                reason=ev.reason,
            )

    async def _publish_live(self, now: datetime, assessments: list[ThreatAssessment]) -> None:
        t = time.monotonic()
        if t - self._last_live < 1.0 / self.settings.live_publish_hz:
            return
        self._last_live = t
        msg = bus.dumps(LiveMessage(site_id=self.site.id, at=now, entities=assessments))
        pipe = self.redis.pipeline()
        pipe.set(bus.live_key(self.site.id), msg, ex=30)
        pipe.publish(bus.live_channel(self.site.id), msg)
        await pipe.execute()

    async def _observe(self, assessments: list[ThreatAssessment]) -> None:
        t = time.monotonic()
        if t - self._last_obs < 1.0 / self.settings.observation_hz or not assessments:
            return
        self._last_obs = t
        async with self.db.session() as session:
            await record_observations(session, assessments)
            await session.commit()

    # ----------------------------------------------------------------- config

    async def config_loop(self) -> None:
        """Hot-reload the tag registry when an admin revokes or edits a tag."""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(bus.config_channel(self.site.id))
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            async with self.db.session() as session:
                cfg = await load_site_config(session, self.site.id)
            self.engine.site.tags.clear()
            self.engine.site.tags.update({t.id: t for t in cfg.tags})
            log.info("tag registry reloaded", tags=len(cfg.tags))

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        tasks = [
            asyncio.create_task(self.mqtt_loop(), name="mqtt"),
            asyncio.create_task(self.tick_loop(), name="tick"),
            asyncio.create_task(self.config_loop(), name="config"),
        ]
        await self._stop.wait()
        for task in tasks:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks)
        await self.redis.aclose()
        await self.db.dispose()
        log.info("decision service stopped")


async def amain() -> None:
    settings = get_settings()
    configure(settings.log_level, json=settings.env == "prod")
    db = Database(settings.database_url)
    while True:
        async with db.session() as session:
            ids = await site_ids(session)
            if ids:
                cfg = await load_site_config(session, ids[0])
                break
        log.warning("no site seeded yet; waiting (run `make seed`)")
        await asyncio.sleep(5)
    await db.dispose()
    model = DecisionModel.load(settings.decision_model)
    start_http_server(settings.metrics_port_decision)
    log.info(
        "decision service starting",
        site=cfg.site.id,
        model=model.fusion.version,
        tick_hz=settings.decision_tick_hz,
    )
    await DecisionService(settings, Site(cfg), model, _load_scorer(settings)).run()


def main() -> None:
    asyncio.run(amain())
