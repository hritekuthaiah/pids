# Runbook — demo day

## The day before

1. `git pull && make setup`. Start Docker Desktop.
2. Paste `ANTHROPIC_API_KEY` into `.env` for the agent. Keep it out of chat and git.
3. Build and install the guard app on each team phone
   (see [apps/guard/README.md](../../apps/guard/README.md)), then sign in once.
4. Print the floor markers: `uv run pids-edge markers --out markers --ids 0-5`.
5. Rehearse the whole [script](../demo/script.md) at least twice, with `make demo-reset`
   between runs.

## In the room (T−60 min)

1. **Measure the room.** Edit `config/sites/demo-room.yaml`: room polygon, secure core,
   camera position and heading. Tape the zone outlines on the floor so the audience
   can see them.
2. **Mount the camera** high in a corner. Use `make edge-cameras` to find its index and
   set it in `config/edge/edge-01.yaml`.
3. **Calibrate.** Lay the markers on the surveyed points in
   `config/edge/edge-01.marks.yaml`, then run
   `uv run pids-edge calibrate --marks config/edge/edge-01.marks.yaml`. Check the zones
   drawn on the image sit on the tape, and aim for an RMS error under 0.15 m. Pick up
   the markers.
4. **Bring it up:** `make demo`. It prints the console URL and the guard-app server
   address.
5. **Start the edge node** in its own terminal with `make edge`. Allow camera and
   Bluetooth access when macOS asks.
6. **Optional:** `make obs` for Grafana on a second screen (admin password in `.env`).
7. **Phones.** Connect them to the same Wi-Fi as the laptop. Open the app and check
   the feed chip reads "open". Turn on Badge and Share position.

## T−10 min checks

- [ ] Console shows the room, both zones and the live camera panel.
- [ ] Walk through once: a track appears where you stand (within ~0.3 m of the tape).
- [ ] A badge holder walking in gets `ble:` in sources within ~10 s.
- [ ] Stepping into the secure core raises CRITICAL, sounds the console alarm and
      buzzes the guard's phone.
- [ ] Agent triage returns a report (or the panel says the agent is off).
- [ ] `make demo-reset` to start from a clean slate.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `camera ... did not open` / OpenCV "not authorized" | macOS camera permission for the terminal app: System Settings → Privacy & Security → Camera. |
| Badge never links | Bluetooth permission for the terminal app. Phone Badge on (Android 12+ needs "Nearby devices"). The badge holder must *move*: standing still gives no evidence, by design. |
| Track positions are off | Camera bumped: re-run calibration. |
| Phone: "Sign-in failed" / feed reconnecting | Phone on another network, or the Mac firewall blocks port 8000. Use the address `make demo` printed. |
| Edge on another machine can't connect | `make certs SAN="<laptop LAN IP>"`, restart the broker (`make demo`), copy `infra/certs/out/ca.crt` to the edge, and set `MQTT_CA_FILE`. |
| Console blank / API unhealthy | `make ps`, `make logs`. `make demo` again is idempotent. |
| Old alerts everywhere | `make demo-reset`. |

## After

`make down`. Data volumes are kept; `make nuke` wipes them.
