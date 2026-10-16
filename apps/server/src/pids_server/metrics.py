"""Prometheus metrics. Pipeline latency is measured per hop from message traces."""

from __future__ import annotations

from datetime import datetime

from prometheus_client import Counter, Gauge, Histogram

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)

PIPELINE_LATENCY = Histogram(
    "pids_pipeline_latency_seconds",
    "Time between pipeline hops, from per-message traces",
    ["hop"],
    buckets=_LATENCY_BUCKETS,
)
STEP_SECONDS = Histogram(
    "pids_decision_step_seconds", "Wall time of one decision-engine step", buckets=_LATENCY_BUCKETS
)
MESSAGES = Counter("pids_messages_total", "Telemetry messages consumed", ["stream", "result"])
ALERT_EVENTS = Counter("pids_alert_events_total", "Alert state-machine events", ["kind", "level"])
ENTITIES = Gauge("pids_entities_assessed", "Entities assessed in the last step", ["site"])
HTTP_SECONDS = Histogram(
    "pids_http_request_seconds",
    "API request duration by route template (bounded cardinality)",
    ["method", "route", "status"],
    buckets=_LATENCY_BUCKETS,
)
NOTIFICATIONS = Counter(
    "pids_notifications_total", "Notification dispatches", ["channel", "status"]
)


def observe_trace(trace: dict[str, datetime], hops: list[tuple[str, str]]) -> None:
    for start, end in hops:
        if start in trace and end in trace:
            dt = (trace[end] - trace[start]).total_seconds()
            if dt >= 0:
                PIPELINE_LATENCY.labels(hop=f"{start}->{end}").observe(dt)
