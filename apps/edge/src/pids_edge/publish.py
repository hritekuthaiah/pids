"""MQTT telemetry publisher with store-and-forward across link loss (NFR-05).

While the broker is unreachable, messages wait in a bounded outbox. On reconnect,
only messages young enough to still mean something are sent: a track position from
a minute ago would be ingested as stale, so it is dropped (and counted) rather than
replayed. The decision engine also ignores out-of-order batches per track, so a
short replay is safe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.reasoncodes import ReasonCode

log = logging.getLogger("pids_edge.publish")


@dataclass(frozen=True, slots=True)
class Message:
    topic: str
    payload: bytes
    qos: int
    retain: bool
    queued_at: float


class Outbox:
    """Bounded FIFO of unsent messages; the oldest are evicted first when full."""

    def __init__(
        self, limit: int, replay_window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._items: deque[Message] = deque(maxlen=limit)
        self._window = replay_window_s
        self._clock = clock
        self.evicted = 0
        self.expired = 0

    def __len__(self) -> int:
        return len(self._items)

    def put(self, topic: str, payload: bytes, qos: int = 1, retain: bool = False) -> None:
        if len(self._items) == self._items.maxlen:
            self.evicted += 1
        self._items.append(Message(topic, payload, qos, retain, self._clock()))

    def drain(self) -> list[Message]:
        """Everything still fresh, oldest first; stale messages are discarded."""
        now = self._clock()
        fresh = [m for m in self._items if now - m.queued_at <= self._window]
        self.expired += len(self._items) - len(fresh)
        self._items.clear()
        return fresh


class MqttPublisher:
    """One edge node's connection to the broker (username = node id, per the ACL)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        client_id: str,
        outbox: Outbox,
        will: tuple[str, bytes] | None = None,
    ) -> None:
        self.outbox = outbox
        self._lock = threading.Lock()
        self._connected = False
        self.sent = 0
        c = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id)
        c.username_pw_set(username, password)
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        if will is not None:
            c.will_set(will[0], will[1], qos=1, retain=True)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        self._client = c
        self._host, self._port = host, port
        self.on_connected: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=15)
        self._client.loop_start()

    def _on_connect(
        self, client: mqtt.Client, userdata: Any, flags: Any, reason: ReasonCode, props: Any
    ) -> None:
        del client, userdata, flags, props
        if reason.is_failure:
            log.error("broker refused connection: %s", reason)
            return
        with self._lock:
            self._connected = True
            backlog = self.outbox.drain()
            for m in backlog:
                self._client.publish(m.topic, m.payload, qos=m.qos, retain=m.retain)
        log.info(
            "connected to %s:%d (replayed %d, dropped %d stale)",
            self._host,
            self._port,
            len(backlog),
            self.outbox.expired,
        )
        if self.on_connected:
            self.on_connected()

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, flags: Any, reason: ReasonCode, props: Any
    ) -> None:
        del client, userdata, flags, props
        with self._lock:
            self._connected = False
        log.warning("disconnected from broker (%s); buffering", reason)

    def publish(self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False) -> None:
        with self._lock:
            if self._connected:
                info = self._client.publish(topic, payload, qos=qos, retain=retain)
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    self.sent += 1
                    return
            self.outbox.put(topic, payload, qos, retain)

    def stop(self, final: tuple[str, bytes] | None = None) -> None:
        if final is not None and self._connected:
            self._client.publish(final[0], final[1], qos=1, retain=True).wait_for_publish(2.0)
        self._client.disconnect()
        self._client.loop_stop()
