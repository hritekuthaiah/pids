# Live demo script — 27 Oct 2026

Everything below happens live, with real people, a real camera and a real phone.
Simulator and evaluation numbers are shown as evaluation results, never presented as
the live system.

**Roles:** *Operator* (at the console, signed in as `admin@pids.local`), *Guard* (phone
in hand), *Badge holder* (authorised teammate, phone acting as a badge), *Intruder* (no
badge), *Narrator*.

**Room:** the "compound" is the room — 8 m × 6 m in `config/sites/demo-room.yaml`. The
camera is **a spare Android phone** wedged high in the north-west corner, streaming over
the LAN; the laptop sits at the operator's desk and never has to look at anything. Three
outlines are taped on the floor: the watched floor (warning), the secure core (critical,
a desk standing in for a vault), and — in a second colour — the core the operator will
redraw to in Act 6.

Setup and calibration detail lives in the [runbook](../runbooks/demo-day.md); the
[pre-flight](#pre-flight) below is the short version that must be true before you start.

## Running order

| # | Act | Min | The audience is watching |
|---|---|---|---|
| 0 | [The problem](#act-0--the-problem) | 1 | Slide |
| 1 | [The quiet perimeter](#act-1--the-quiet-perimeter) | 1.5 | Console: map, camera panel, baseline counter |
| 2 | [Where the camera is looking](#act-2--where-the-camera-is-looking) | 2 | Camera footprint on the map; a click in the image becoming a pin |
| 3 | [An authorised person walks in](#act-3--an-authorised-person-walks-in) | 2 | The badge holder, and their track's sources |
| 4 | [An intruder slips in alongside](#act-4--an-intruder-slips-in-alongside) | 3 | Two tracks diverging; time-to-breach; the critical banner |
| 5 | [The response](#act-5--the-response) | 2.5 | The guard's phone, then the agent's triage |
| 6 | [The zones are not baked in](#act-6--the-zones-are-not-baked-in) | 2.5 | The operator drawing a new critical zone, and the next walk judged against it |
| 7 | [The evidence](#act-7--the-evidence) | 2 | Slides + Grafana |
| — | [Outdoors with GPS](#optional--outdoors-with-gps) | 2 | Optional |

**≈16.5 min**, or ≈18.5 with the GPS segment. Leave Act 6 in: it is the beat that shows
the system is operated, not configured once and frozen.

## Pre-flight

### The day before

- [ ] `git pull && make setup`, Docker Desktop running.
- [ ] **`ANTHROPIC_API_KEY` pasted into `.env`.** Without it the agent falls back to
      Ollama if `OLLAMA_BASE_URL` is set; with neither, the triage panel reads *"The
      agent is off: no LLM is configured. Alerting is unaffected."* That is a survivable
      demo — say it is by design — but Act 5 is much better with a key.
- [ ] **Guard APK installed on each phone** (USB debugging, see
      [apps/guard/README.md](../../apps/guard/README.md)), signed in once.
- [ ] **The phone-as-camera path tried at least once on the real phone** — it has never
      run on real hardware before today. Tap *Use this phone as a camera* → *Start
      camera*, allow Camera and notifications, and confirm the screen shows a URL. Camera2
      frame packing differs by device: if the stream is a green smear on one phone, try
      another, or fall back to any third-party IP-camera app (it is just another URL,
      ADR-0013).
- [ ] `make edge-model` has been run — `apps/edge/models/yolo26n.onnx` must exist.
- [ ] Print the floor markers: `uv run pids-edge markers --out markers --ids 0-5`.
- [ ] Rehearse the whole script twice, `make demo-reset` between runs.

### In the room (T−60 min)

1. **Phone and laptop on the same Wi-Fi.** No VPN on either. This is the single most
   common cause of a dead demo.
2. **Put the site on the room and measure it.** Edit `config/sites/demo-room.yaml` (the two
   zone polygons, the camera position and heading, and **`site.origin`** set to the room's
   real coordinates) — or sign in as admin and use *Edit zones → Site location* (*Use my
   location*, typed coordinates, or *Pick on map*) and the *Corners* table, then
   `make site-export` to keep it. Set the origin *now*, not on stage — moving it live
   rebuilds the decision engine and drops live tracks. Full steps:
   [demo-day runbook](../runbooks/demo-day.md).
3. **Tape the floor:** the watched floor, the secure core, and the second core for Act 6
   in a different colour.
4. **Stand the phone up as the camera.** Wedge it high in a corner, lens across the room,
   **plugged in**, screen staying on. In the app: *Use this phone as a camera* → *Start
   camera*. Read the URL off the *"Type this on the laptop"* panel — it looks like
   `http://192.168.0.105:8081/stream.mjpg` (port **8081**).
5. **Check the stream** from the laptop before trusting it:

   ```bash
   make camera-test URL=http://192.168.0.105:8081/stream.mjpg
   ```

   It prints the resolution, the median frame rate and dropped frames, and warns below
   8 fps. If it cannot connect it prints the checklist rather than hanging.
6. **Point the edge node at the phone in config**, not on the command line: set
   `camera.source` in `config/edge/edge-01.yaml` to that URL. This matters because
   `pids-edge calibrate` has no `--source` flag — it reads `camera.source`, and the
   homography must be fitted through the camera that will actually run.
7. **Calibrate** — the demo does not start without this; there is no calibration file in
   the repo and the edge node refuses to run without one:

   ```bash
   uv run pids-edge calibrate --marks config/edge/edge-01.marks.yaml
   ```

   Lay the printed markers on the six surveyed points, freeze a frame, check the zones
   drawn on the image sit on the tape, aim for **RMS under 0.15 m**, save. Pick the
   markers up. Re-run it if the phone is bumped — the mapping belongs to *that* lens in
   *that* position.
8. **Bring the stack up:** `make demo`. It prints the console URL (`:8080`) and the
   guard-app server address.
9. **Start the edge node** in its own terminal: `make edge` (it uses the phone URL from
   step 6). If the phone's IP moved since calibration, `make edge SOURCE=http://<new-ip>:8081/stream.mjpg`
   — same camera, new address, calibration still valid.
10. **Permissions.** Grant **Bluetooth** to the terminal app when macOS asks: badges do
    not work without it. **Camera** permission is not needed for a phone stream, but
    grant it anyway — it is what the webcam fallback needs, and you do not want to be
    clicking a system dialog under pressure.
11. **Sign in to the console as `admin@pids.local`.** The *Edit zones* button is
    admin-only; as `operator@pids.local` Act 6 is impossible.
12. Optional: `make obs` for Grafana on a second screen.
13. **Prepare the webcam fallback** (10 minutes now, saves the demo later): copy
    `config/edge/edge-01.yaml` to `config/edge/edge-01-webcam.yaml`, set `camera.source: 0`
    and `ground.calibration: config/edge/edge-01-webcam.calibration.yaml`, then calibrate
    the laptop webcam into that file:

    ```bash
    uv run pids-edge calibrate --config config/edge/edge-01-webcam.yaml --marks config/edge/edge-01.marks.yaml
    ```

    The fallback then costs one command. Without its own calibration the webcam still
    detects people but puts them in the wrong place on the map.

### T−10 min checks

- [ ] Console shows the room, both zones, and the camera panel chip reading **live**.
- [ ] The *Live camera* panel lists the phone under **Phone cameras offered**, with its URL.
- [ ] *Sensor cover* is on and the camera's **footprint** is drawn on the map.
- [ ] The camera panel footer reads *"Click the image to put that spot on the map."*
- [ ] Walk through once: a track appears where you stand, within ~0.3 m of the tape.
- [ ] A badge holder walking in gets `ble:` in sources within ~10 s.
- [ ] Stepping into the secure core raises CRITICAL, sounds the console alarm and buzzes
      the guard's phone.
- [ ] Agent triage returns a report (or says the agent is off).
- [ ] `make demo-reset`, and **Reset** on the baseline counter, for a clean slate.

## Act 0 — The problem

**1 min · slide.**

Plain geofences either miss intruders who carry no device, or alarm at every dog, shadow
and patrol. PIDS fuses geofence, camera, behaviour and passive identity into one
calibrated decision.

## Act 1 — The quiet perimeter

**1.5 min · the console on the projector.**

- **Show:** the map of the room with both zones, the *Live camera* panel (the edge node's
  annotated view, zones drawn on the image), and *Naive geofence vs PIDS* at **0 / 0**.
- **Point at** the *Phone cameras offered* line under the camera panel, and then at the
  phone in the corner.
- **Narrator:** "That camera is a phone. It streams to this laptop over the room's Wi-Fi
  and nothing else — nothing is recorded on the phone, and no video reaches the server.
  The laptop runs YOLO on its CPU at about 20 ms a frame. Everything you are about to see
  is live."

## Act 2 — Where the camera is looking

**2 min · the map, then the camera image.** *Give this its own moment — it is the answer
to "does it really know where it's looking?"*

- **Do:** with *Sensor cover* on, point at the shaded wedge on the map. It is not a
  drawing of the camera's spec sheet: the edge node walked its own image border,
  projected each sample onto the floor and published the polygon it can actually see.
- **Do:** click a spot on the floor in the live camera image — the far corner, or a chair.
  A pin drops on the map at that place and the footer reads the position, e.g.
  `13.262044, 77.420071 · 5.2 m E, 3.1 m N from the site origin`. The map eases across
  to the pin.
- **Do:** have someone stand on the pinned spot, so the audience sees the pin and the
  person in the same place.
- **Do:** now click the ceiling, or a wall above the horizon. The footer says *"That is
  above the horizon — no point on the ground."*
- **Narrator:** "The camera image and the map are the same place. The node published the
  homography it calibrated this afternoon, so a pixel is a position — and where it cannot
  know, it says so instead of guessing."

## Act 3 — An authorised person walks in

**2 min · the badge holder, and the track's detail panel.**

- **Badge holder** walks in from the door, across the floor, toward the camera corner.
- **Expect:**
  - A track appears.
  - Within a few seconds its sources show `ble:badge-team-1` and the identity reads
    authorised.
  - Its level stays nominal or elevated, with no alarm.
  - **Naive geofence** goes up; **PIDS (alerting)** does not.
- **Narrator:** "Nobody tapped anything. The phone advertises a code that changes every
  30 seconds. The system linked it to *this* person because the signal strength rose as
  they walked toward the reader, and only theirs did. A plain geofence would have alarmed
  on a colleague — that counter on the left is doing exactly that."

## Act 4 — An intruder slips in alongside

**3 min · two tracks on the map, the fusion breakdown, then the banner.**

- **Intruder** enters right next to the badge holder, and they walk together.
- **Expect:** while they walk side by side, *nobody* is whitelisted. The fusion panel
  shows no authorised-tag term on either track, because the badge cannot tell them apart.
- **Narrator:** "If in doubt, nobody is trusted. A missed intruder is the worst failure."
- They split up. The badge holder goes back to their desk; the intruder heads for the
  secure core.
- **Expect:**
  - The badge stays with the badge holder.
  - The intruder goes ELEVATED → WARNING with a *predicted breach* (time-to-breach counts
    down), then CRITICAL on entering the core.
  - The console alarm sounds and the critical banner appears.
  - **The guard's phone buzzes.**
- **Narrator:** point at the fusion breakdown — why the score is what it is — and at the
  baseline counter, which has by now counted both of them while PIDS raised one.

## Act 5 — The response

**2.5 min · the guard's phone on the document camera, then the console.**

- **Guard** opens the alert: *What to do*, *Why*, *Where* with distance and direction,
  then taps **Acknowledge — on my way**.
- **Operator** clicks **Ask the agent**.
  - Claude reviews the evidence with read-only tools and recommends actions, citing the
    site procedures (SOP-01 §1).
  - The operator clicks **Approve** on one recommendation. Nothing happens without that
    click — the agent is off the alerting path and cannot act.
  - Open **Incident report draft** and **Copy**.
- **Operator** types into *Ask the log*: "critical alerts in the secure core today". The
  answer shows how the question was understood.
- **Guard** taps **Resolved**.

## Act 6 — The zones are not baked in

**2.5 min · the map, the editing panel, then the floor.** *This is the most demonstrable
thing in the build.*

- **Say first:** "A real site changes. A vault gets moved; a contractor needs a corner
  fenced off for a week. Here is what that costs." Then do it in front of them.
- **Do:** click **Edit zones**. Delete *Secure Core* with its ✕, click **+ critical**,
  and click the corners of the second taped outline on the map — the panel counts down
  the corners it still needs, double-click or Enter closes the ring, Backspace undoes a
  corner, Esc cancels. Rename it *Secure Core*. The row shows its area in m².
- **Do:** click **Save zones**. No restart, no redeploy. If a second console is open on
  another screen, it redraws there too without a reload.
- **Do:** have the **intruder walk the same path again** — through the old core, which is
  now ordinary floor, and then into the new one.
- **Expect:** walking over the old outline raises nothing. Entering the new one raises
  CRITICAL, with the banner and the guard's phone again. The live tracks that were
  already on the map survived the edit — only the geometry they are judged against
  changed.
- **Narrator:** "That took fifteen seconds and the system never went down. The engine
  adopted the new zones in place, every open console was told to refetch, and the edit is
  in the audit log against the admin who made it."
- **Optional aside, if you want to show the guard rails:** try saving with no critical
  zone at all. The server refuses it and the panel shows why — a site without a critical
  zone has nothing to call an intrusion.

## Act 7 — The evidence

**2 min · slides + Grafana.**

- **Evaluation** ([results.md](../evaluation/results.md)), on 160 held-out scenarios:
  PIDS detects **99.3 %** of intrusions (139/140) against 100 % for naive line-crossing,
  with **82 % fewer nuisance alarms** and a 68.7 s median lead.
  - Ablations show identity tags cut nuisance alarms.
  - Ablations show breach prediction and the safety rails protect recall.
- **Edge** ([detector.md](../evaluation/detector.md)): the ONNX export runs at 19.8 ms
  p50 against PyTorch's 49.2 ms — **2.5× faster, CPU only**, for 0.397 vs 0.402 mAP, so
  no accuracy worth the name was lost.
- **Grafana** (`make obs`, dashboard *PIDS — operations*): capture → decision latency is
  about **170 ms**, against the 2 s budget (NFR-01).
- **Say:** the live demo shows a handful of entities in one room; larger scale is
  characterised in simulation and reported separately.

## Optional — Outdoors with GPS

**2 min.** A teammate carries the GPS module (`make gps`, after `make gps-probe` has
identified it) or shares the guard app's position with **Share position**. The cooperative
tag appears on the map and links to the camera track when in view.

## If something fails

| Failure | Do this |
|---|---|
| Phone stream won't open | `make camera-test URL=…` and read its checklist: same Wi-Fi, streaming screen open and awake, URL copied exactly, no VPN. A third-party IP-camera app is just another URL. |
| Phone drops mid-demo | The edge reconnects after 3 failed reads; the camera chip goes offline, then live. If it does not come back: `make edge EDGE_CONFIG=config/edge/edge-01-webcam.yaml` (prepared in pre-flight step 13). |
| Webcam fallback, not prepared | `make edge SOURCE=0` still detects people, but positions will be wrong — the calibration belongs to the phone. Say so rather than letting the map lie, and lean on the camera panel instead of the map. |
| Camera panel says offline but the edge is running | The panel probes `/snapshot.jpg` every 5 s. Check the edge's own preview at <http://127.0.0.1:8090/stream.mjpg>, then **Retry now**. |
| No footprint on the map, no "click the image" footer | No `NodeView` has arrived. The node publishes one with its health every 5 s *after* calibration — check the edge node started and that the calibration file in `config/edge/edge-01.yaml` exists. |
| No **Edit zones** button | You are signed in as the operator. It is admin-only: `admin@pids.local`. |
| **Save zones** refused | Read the message — at least one critical zone must remain, ids must be unique, and no asset tag may be left pointing at a deleted containment zone. Draw the replacement before deleting the old one. |
| Tracks are in the wrong place | The phone was bumped. Re-calibrate, or carry on and say the mapping is surveyed to that position. |
| Phone gets no alert | Phone and laptop on the same Wi-Fi, and the app's feed chip reads "open". The console alarm still shows the detection. |
| Badge not linking | Bluetooth permission for the terminal app; the app shows *Badge: on*. The badge holder must **move** — standing still gives no evidence, by design. |
| Camera won't open / OpenCV "not authorized" | macOS camera permission for the terminal app (System Settings → Privacy & Security → Camera). Only the webcam path needs it. |
| Agent unavailable | The panel says the agent is off. Alerting is unaffected; say so, it's by design. |
| Everything is confused after rehearsals | `make demo-reset`, and **Reset** on the baseline counter. |
