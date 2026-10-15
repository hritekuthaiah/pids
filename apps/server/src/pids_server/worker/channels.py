"""Response channels (PLT-06). Each takes an alert and reports what happened.

Mobile push is real (Expo push service -> FCM). Email and SMS are dispatch
stubs that record the message they would send — wired to the same interface so a
provider is a drop-in. The siren is a real MQTT command to the edge node(s).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import aiomqtt
import httpx

from pids_server import bus
from pids_server.schemas import AlertOut

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass(frozen=True, slots=True)
class Dispatch:
    status: str  # sent | skipped | failed
    detail: dict[str, Any]


class Channel(Protocol):
    name: str

    async def send(self, alert: AlertOut, recipients: list[str]) -> Dispatch: ...


def headline(a: AlertOut) -> tuple[str, str]:
    where = a.zone_id or "open ground"
    title = f"{a.level.upper()} — {a.entity_class} in {where}"
    body = a.reason
    if a.assessment.time_to_breach_s is not None and a.zone_id != "compound-critical":
        body = f"Predicted breach in {a.assessment.time_to_breach_s:.0f}s. {body}"
    return title, body


class ExpoPush:
    name = "push"

    def __init__(self, client: httpx.AsyncClient, access_token: str | None) -> None:
        self.client = client
        self.access_token = access_token

    async def send(self, alert: AlertOut, recipients: list[str]) -> Dispatch:
        if not recipients:
            return Dispatch("skipped", {"reason": "no registered devices"})
        title, body = headline(alert)
        messages = [
            {
                "to": token,
                "title": title,
                "body": body,
                "sound": "default",
                "priority": "high",
                "channelId": "alerts",
                "data": {"alert_id": alert.id, "level": alert.level, "site_id": alert.site_id},
            }
            for token in recipients
        ]
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            r = await self.client.post(EXPO_PUSH_URL, json=messages, headers=headers, timeout=10)
            r.raise_for_status()
            tickets = r.json().get("data", [])
        except httpx.HTTPError as exc:
            return Dispatch("failed", {"error": str(exc), "devices": len(recipients)})
        errors = [t for t in tickets if t.get("status") != "ok"]
        return Dispatch(
            "sent" if not errors else "failed",
            {"devices": len(recipients), "errors": errors[:5]},
        )


class Siren:
    name = "siren"

    def __init__(self, mqtt: aiomqtt.Client, node_ids: list[str]) -> None:
        self.mqtt = mqtt
        self.node_ids = node_ids

    async def send(self, alert: AlertOut, recipients: list[str]) -> Dispatch:
        del recipients
        payload = bus.dumps({"alert_id": alert.id, "level": alert.level, "seconds": 20})
        for node in self.node_ids:
            await self.mqtt.publish(bus.mqtt_command(alert.site_id, node, "siren"), payload, qos=1)
        return Dispatch("sent", {"nodes": self.node_ids})


class RecordedMessage:
    """Email/SMS stand-in: records the exact message a provider would deliver."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def send(self, alert: AlertOut, recipients: list[str]) -> Dispatch:
        title, body = headline(alert)
        return Dispatch("recorded", {"to": recipients, "subject": title, "body": body})
