"""Stream a scenario to the MQTT broker in real time, as if from real edge nodes.

Used for demos and integration testing: the decision service cannot tell these
messages from hardware. Authenticates as the development-only ``pids-sim`` user.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from pids_core.site import Site
from pids_sim.runner import frames
from pids_sim.scenarios import ScenarioSpec, build
from pids_sim.sensors import SensorParams

log = logging.getLogger("pids_sim.live")


def stream(
    site: Site,
    spec: ScenarioSpec,
    host: str,
    port: int,
    username: str,
    password: str,
    frame_dt: float = 0.2,
) -> None:
    """Real time only: the decision engine runs on the wall clock, so accelerated
    playback would make every entity appear proportionally faster."""
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"pids-sim-{spec.seed}")
    client.username_pw_set(username, password)
    client.connect(host, port, keepalive=30)
    client.loop_start()
    try:
        scenario = build(site, spec)
        scenario.start = datetime.now(UTC)
        _, stream_frames = frames(site, scenario, replace(SensorParams(), frame_dt=frame_dt))
        t0 = time.monotonic()
        threat = next((a.role.value for a in scenario.agents if a.is_threat), "none")
        # Like a real edge node, make tracker ids unique per run (trackers restart at 1).
        boot = f"{int(time.time()) % 100_000:05d}"
        log.info("streaming %s seed=%d threat=%s", spec.family.value, spec.seed, threat)
        for frame in stream_frames:
            delay = t0 + frame.t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            now = datetime.now(UTC)
            for b in frame.batches:
                tracks = [
                    t.model_copy(update={"track_id": f"{boot}-{t.track_id}"}) for t in b.tracks
                ]
                b2 = b.model_copy(
                    update={"captured_at": now, "trace": {"captured": now}, "tracks": tracks}
                )
                client.publish(f"pids/{site.id}/{b.node_id}/tracks", b2.model_dump_json(), qos=1)
            for f in frame.fixes:
                f2 = f.model_copy(update={"at": now, "trace": {"captured": now}})
                client.publish(f"pids/{site.id}/gps-sim/gps", f2.model_dump_json(), qos=1)
            for r in frame.reads:
                r2 = r.model_copy(update={"at": now, "trace": {"captured": now}})
                client.publish(f"pids/{site.id}/{r.reader_id}/sensors", r2.model_dump_json(), qos=1)
    finally:
        client.loop_stop()
        client.disconnect()
