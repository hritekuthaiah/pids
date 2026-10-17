# Runbook — demo day

How the room gets built. The [script](../demo/script.md) is what you say and do on
stage; this is the setup behind it. The script's [pre-flight](../demo/script.md#pre-flight)
is the checklist you tick on the day — do not duplicate it here; this runbook is the
detail behind the hard steps: standing the phone up as the camera, pointing the edge node
at it *before* calibrating, calibrating, and keeping a webcam fallback ready.

The camera is **a spare Android phone** streaming MJPEG over the room's Wi-Fi (ADR-0013),
not a USB webcam. The webcam is the documented fallback, below.

## The day before

1. `git pull && make setup`. Start Docker Desktop.
2. Paste `ANTHROPIC_API_KEY` into `.env` for the agent. Keep it out of chat and git.
   (Without it the agent falls back to Ollama if `OLLAMA_BASE_URL` is set; with neither,
   the triage panel says the agent is off and alerting is unaffected — survivable, but
   Act 5 is much better with a key.)
3. Build and install the guard app on each team phone (USB debugging, see
   [apps/guard/README.md](../../apps/guard/README.md)), then sign in once. The same app
   carries the BLE badge **and** the `pids-camera` service — one install does both.
4. **Try the phone-as-camera path once on a real phone** — it has never run on real
   hardware before. Tap *Use this phone as a camera* → *Start camera*, allow Camera and
   notifications, and confirm the screen shows a URL. Camera2 frame packing differs by
   device: if the stream is a green smear, try another phone, or fall back to any
   third-party IP-camera app (it is just another MJPEG URL — ADR-0013).
5. Export the detector: `make edge-model`. Confirm `apps/edge/models/yolo26n.onnx` exists
   (the edge node will not start without it).
6. Print the floor markers: `uv run pids-edge markers --out markers --ids 0-5`.
7. Rehearse the whole [script](../demo/script.md) at least twice, with `make demo-reset`
   between runs.

## In the room (T−60 min)

Do these in order. Steps 4–7 are the ones that go wrong under pressure.

1. **Network.** Phone and laptop on the **same Wi-Fi**, **no VPN** on either. This is the
   single most common cause of a dead demo.
2. **Put the site on the room, then measure it.** Either edit `config/sites/demo-room.yaml`
   (zone polygons, camera position and heading, and **`site.origin`** set to the room's
   real coordinates) — or do it in the console, which is quicker:

   1. Sign in as `admin@pids.local` → **Edit zones** → **Site location**.
   2. Stand at the room's **south-west floor corner** and press **Use my location**, or
      type / paste the coordinates (`13.262000, 77.420000` pasted into the latitude box
      fills both), or switch to *Satellite*, zoom right in and **Pick on map** on the
      corner. A laptop's fix is often ±20–100 m: when the panel says so, pick on the map.
   3. Leave *Move the zones and cameras with it* ticked: the whole 8 × 6 m site lands on
      that corner at its real size. Fix any corner with the **Corners** table (type
      latitude/longitude) or drag it; **Add a zone from coordinates** takes a pasted
      survey list.
   4. **Save zones**, then **keep it**: `make site-export` writes it into
      `config/sites/demo-room.yaml`. Without this the next `make demo` re-seeds the
      placeholder, *and* the camera node keeps reading the old origin (its footprint and
      tracks land in the wrong place). Restart the edge node after exporting.

   **Set the origin now, never on stage** — moving it live rebuilds the decision engine and
   drops live tracks (redrawing zones alone is safe; moving the origin is not).
3. **Tape the floor:** the watched floor, the secure core, and — in a second colour — the
   core the operator will redraw to in Act 6.
4. **Stand the phone up as the camera.** Wedge it high in a corner, lens across the room,
   **plugged in**, screen staying on. In the guard app: *Use this phone as a camera* →
   *Start camera*. Read the LAN URL off the *"Type this on the laptop"* panel — it looks
   like `http://192.168.0.105:8081/stream.mjpg`. The port is **8081** (8080 is the
   console; do not confuse them).
5. **Verify the stream from the laptop before trusting it:**

   ```bash
   make camera-test URL=http://192.168.0.105:8081/stream.mjpg
   ```

   It prints the resolution, median frame rate and dropped frames, and warns below 8 fps.
   If it cannot connect it prints a Wi-Fi/VPN/URL checklist rather than hanging. Do not
   go further until this is green.
6. **Point the edge node at the phone in config — not on the command line.** Set
   `camera.source` in `config/edge/edge-01.yaml` to that URL:

   ```yaml
   camera:
     source: http://192.168.0.105:8081/stream.mjpg
   ```

   This matters because **`pids-edge calibrate` has no `--source` flag** — it opens
   whatever `camera.source` names. Calibrate through the webcam and then run the phone and
   every ground position is silently wrong. Fit the homography through the camera that
   will actually run.
7. **Calibrate.** Hard precondition: there is **no calibration file in the repo**
   (`config/edge/edge-01.calibration.yaml` does not exist) and the edge node refuses to
   run without one. Lay the printed markers on the six surveyed points in
   `config/edge/edge-01.marks.yaml`, then:

   ```bash
   uv run pids-edge calibrate --marks config/edge/edge-01.marks.yaml
   ```

   It opens the phone stream (from `camera.source`), fits the homography, and writes it to
   the `ground.calibration` path in the config (`config/edge/edge-01.calibration.yaml`).
   Freeze a frame, check the zones drawn on the image sit on the tape, aim for **RMS under
   0.15 m**, save. Pick the markers up. Re-run if the phone is bumped — the mapping belongs
   to *that* lens in *that* position.
8. **Bring the stack up:** `make demo`. It prints the console URL (`http://localhost:8080`,
   and the projector/LAN address) and the guard-app server address.
9. **Start the edge node** in its own terminal: `make edge` (it reads the phone URL from
   step 6). If the phone's IP moved since calibration, override just the address —
   calibration still holds because it is the same lens in the same place:

   ```bash
   make edge SOURCE=http://<new-ip>:8081/stream.mjpg
   ```

   There is **no `PIDS_EDGE_SOURCE` env var** — the only overrides are `SOURCE=` (the
   camera) and `EDGE_CONFIG=` (the whole config file).
10. **Permissions.** When macOS asks, grant **Bluetooth** to the terminal app — badges do
    not work without it. **Camera** permission is not needed for a phone stream, but grant
    it anyway: it is what the webcam fallback needs, and you do not want to be clicking a
    system dialog under pressure.
11. **Sign in to the console as `admin@pids.local`.** The *Edit zones* button is
    admin-only; as `operator@pids.local` Act 6 is impossible. (Seeded users:
    `admin@` / `operator@` / `guard.alpha@` / `guard.bravo@`; passwords are the `SEED_*`
    values in `.env`.)
12. **Optional:** `make obs` for Grafana on a second screen (admin password in `.env`).

### Webcam fallback (prepare now — 10 minutes saves the demo later)

The webcam needs its **own** calibration: a different lens and position, so the phone's
homography does not transfer, and there is no `--calibration` override on `run`. Keep a
second edge config so the fallback costs one command on the day:

1. Find the webcam's index: `make edge-cameras`.
2. Copy `config/edge/edge-01.yaml` to `config/edge/edge-01-webcam.yaml`; set
   `camera.source` to that index (usually `0`) and
   `ground.calibration: config/edge/edge-01-webcam.calibration.yaml`.
3. Calibrate the webcam into that file (point the camera across the room first):

   ```bash
   uv run pids-edge calibrate --config config/edge/edge-01-webcam.yaml --marks config/edge/edge-01.marks.yaml
   ```

Then, if the phone fails mid-demo, switch with `make edge EDGE_CONFIG=config/edge/edge-01-webcam.yaml`.
Without its own calibration the webcam still detects people but puts them in the wrong
place on the map.

## T−10 min checks

Build acceptance — the room is ready when all of these are true. (The full dress
run-through lives in the script's [pre-flight](../demo/script.md#pre-flight); this is the
new-feature sign-off.)

- [ ] Signed in as **`admin@pids.local`** and the **Edit zones** button is visible.
- [ ] Console shows the room, both zones, and the *Live camera* panel chip reads **live**.
- [ ] The camera's **footprint** (the shaded wedge) is drawn on the map. If it is missing,
      the node has not published its `NodeView` yet — it rides with health every ~5 s
      *after* calibration, so give it a moment; a lasting gap means the edge node did not
      start or the calibration file is missing.
- [ ] The camera panel footer reads *"Click the image to put that spot on the map."*, and
      a click in the image drops a pin on the map.
- [ ] A **zone edit saves cleanly**: Edit zones → nudge a corner → Save zones, no restart,
      no error. Undo the nudge afterwards.
- [ ] Walk through once: a track appears where you stand, within ~0.3 m of the tape.
- [ ] A badge holder walking in gets `ble:` in sources within ~10 s.
- [ ] Stepping into the secure core raises CRITICAL, sounds the console alarm and buzzes
      the guard's phone.
- [ ] Agent triage returns a report (or the panel says the agent is off).
- [ ] `make demo-reset`, and **Reset** on the baseline counter, for a clean slate.

## Troubleshooting

Build-time failures, in the order you hit them. Stage-time failures are in the script's
[If something fails](../demo/script.md#if-something-fails) table.

| Symptom | Cause / fix |
|---|---|
| Phone stream won't open | `make camera-test URL=…` and read its checklist: same Wi-Fi, streaming screen open and awake, URL copied exactly (port **8081**, not 8080), no VPN. A third-party IP-camera app is just another URL. |
| Phone stream is a green smear | Camera2 stride differs by device. Try another phone, or a third-party IP-camera app (ADR-0013). |
| Phone drops mid-demo | The edge reconnects after a few failed reads; the camera chip goes offline, then live. If it does not come back: `make edge EDGE_CONFIG=config/edge/edge-01-webcam.yaml` (prepared above). |
| Tracks are in the wrong place | Calibrated through the wrong camera, or the phone was bumped. Confirm `camera.source` names the phone URL, then re-run `pids-edge calibrate`. |
| `pids-edge run` won't start — no calibration | Expected on a fresh checkout: `config/edge/edge-01.calibration.yaml` does not exist. Calibrate first (step 7). |
| No camera footprint on the map | No `NodeView` has arrived. It publishes with health every ~5 s *after* calibration — check the edge node started and the calibration file in `config/edge/edge-01.yaml` exists. |
| No "Click the image to put that spot on the map" footer | Same cause: no `NodeView` yet. The footer appears once the node has published its view. |
| No **Edit zones** button | You are signed in as the operator. It is admin-only: sign in as `admin@pids.local`. |
| **Save zones** refused | Read the message — at least one critical zone must remain, ids must be unique, and no asset tag may be left pointing at a deleted containment zone. Draw the replacement before deleting the old one. |
| Live tracks vanished after an edit | You moved `site.origin`, which rebuilds the engine. Set the origin in pre-flight (step 2); on stage only redraw zones. |
| Zones / location reverted after `make demo` or a restart | Console edits live in the database; the API re-seeds it from `config/sites/<site>.yaml` on every start. Run `make site-export` after saving (step 2). |
| Camera footprint or tracks sit at the *old* place after moving the site | The edge node still reads the old `site.origin`. `make site-export`, then restart `make edge`. |
| **Use my location** says it is blocked / needs https | The browser must be allowed location (and macOS Location Services for it), and the page must be `localhost` or `https`. The LAN address `http://192.168…` cannot use it: type the coordinates or **Pick on map** instead. |
| Camera won't open / OpenCV "not authorized" | Only the webcam path needs this: macOS camera permission for the terminal app (System Settings → Privacy & Security → Camera). |
| Badge never links | Bluetooth permission for the terminal app; the phone's *Badge* on (Android 12+ needs "Nearby devices"). The badge holder must *move* — standing still gives no evidence, by design. |
| Phone: "Sign-in failed" / feed reconnecting | Phone on another network, or the Mac firewall blocks the API port. Use the server address `make demo` printed. |
| Edge on another machine can't connect | `make certs SAN="<laptop LAN IP>"`, restart the broker (`make demo`), copy `infra/certs/out/ca.crt` to the edge, and set `MQTT_CA_FILE`. |
| Console blank / API unhealthy | `make ps`, `make logs`. `make demo` again is idempotent. |
| Old alerts everywhere | `make demo-reset`. |

## After

`make down`. Data volumes are kept; `make nuke` wipes them.
