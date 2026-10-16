"""``pids-api`` — the REST + WebSocket application."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager

import aiomqtt
import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

from pids_server import __version__
from pids_server.api.routes import agent, alerts, auth, devices, sites
from pids_server.api.ws import Hub
from pids_server.api.ws import router as ws_router
from pids_server.db.session import Database
from pids_server.logs import configure, log
from pids_server.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.db = Database(settings.database_url)
        app.state.redis = Redis.from_url(settings.redis_url)
        app.state.hub = Hub(app.state.redis)
        await app.state.hub.start()
        async with AsyncExitStack() as stack:
            app.state.mqtt = await stack.enter_async_context(
                aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_server_user,
                    password=settings.mqtt_server_password.get_secret_value(),
                    identifier=f"pids-api-{uuid.uuid4().hex[:8]}",
                )
            )
            log.info("api ready", version=__version__)
            yield
        await app.state.hub.stop()
        await app.state.redis.aclose()
        await app.state.db.dispose()

    app = FastAPI(
        title="PIDS API",
        version=__version__,
        description="Autonomous Perimeter Intrusion Detection System",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["server-timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response

    api = "/api/v1"
    app.include_router(auth.router, prefix=api)
    app.include_router(sites.router, prefix=api)
    app.include_router(alerts.router, prefix=api)
    app.include_router(devices.router, prefix=api)
    app.include_router(agent.router, prefix=api)
    app.include_router(ws_router)

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request, response: Response) -> dict[str, str]:
        checks: dict[str, str] = {}
        try:
            async with request.app.state.db.session() as s:
                await s.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "down"
        try:
            await request.app.state.redis.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "down"
        if any(v != "ok" for v in checks.values()):
            response.status_code = 503
        return checks

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def run() -> None:
    settings = get_settings()
    configure(settings.log_level, json=settings.env == "prod")
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 — container network; bind is restricted by compose
        port=8000,
        proxy_headers=True,
        log_config=None,
        ws_ping_interval=20,
    )
