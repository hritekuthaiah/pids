"""Names and payload helpers for the internal message buses.

MQTT carries device telemetry (edge -> platform). Redis carries everything inside
the platform: pub/sub for realtime fan-out to WebSocket clients, a durable stream
for notification jobs, and a key holding the latest live snapshot per site.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import aiomqtt
import orjson
from pydantic import BaseModel

from pids_server.settings import Settings


def mqtt_telemetry(site_id: str, stream: str) -> str:
    """Subscription filter for one telemetry stream from every node of a site."""
    return f"pids/{site_id}/+/{stream}"


def mqtt_publish(site_id: str, node_id: str, stream: str) -> str:
    return f"pids/{site_id}/{node_id}/{stream}"


def mqtt_command(site_id: str, node_id: str, name: str) -> str:
    return f"pids/{site_id}/{node_id}/cmd/{name}"


API_NODE = "api"  # node id under which the API publishes guard-phone GPS fixes


def live_channel(site_id: str) -> str:
    return f"pids:{site_id}:live"


def alerts_channel(site_id: str) -> str:
    return f"pids:{site_id}:alerts"


def config_channel(site_id: str) -> str:
    return f"pids:{site_id}:config"


def live_key(site_id: str) -> str:
    return f"pids:{site_id}:live:latest"


NOTIFY_STREAM = "pids:notify"
NOTIFY_GROUP = "notifiers"


def ws_ticket_key(ticket: str) -> str:
    return f"pids:wsticket:{ticket}"


def dumps(obj: Any) -> bytes:
    """Fast JSON for bus payloads; pydantic models serialise in JSON mode."""
    if isinstance(obj, BaseModel):
        return orjson.dumps(obj.model_dump(mode="json"))
    return orjson.dumps(obj, default=_default)


def _default(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def loads(raw: bytes | str) -> Any:
    return orjson.loads(raw)


def mqtt_client(settings: Settings, identifier: str) -> aiomqtt.Client:
    """The server's broker connection; TLS with the broker certificate verified when a CA
    is configured (MQTT_CA_FILE), as off-host links must be (NFR-03)."""
    return aiomqtt.Client(
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_server_user,
        password=settings.mqtt_server_password.get_secret_value(),
        identifier=identifier,
        tls_context=tls_context(settings.mqtt_ca_file) if settings.mqtt_ca_file else None,
    )


def tls_context(ca_file: Path) -> ssl.SSLContext:
    """Verify the broker's chain and hostname against our CA; TLS 1.2 or newer only."""
    ctx = ssl.create_default_context(cafile=str(ca_file))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx
