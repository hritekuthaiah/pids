# Live demo script — 27 Oct 2026

Everything below happens live, with real people, a real camera and a real phone.
Simulator and evaluation numbers are shown as evaluation results, never presented as
the live system.

**Roles:** *Operator* (at the console), *Guard* (phone in hand), *Badge holder*
(authorised teammate, phone acting as a badge), *Intruder* (no badge), *Narrator*.

**Room:** the "compound" is the room. The camera is high in one corner. Two outlines
are taped on the floor: the watched floor (warning) and the secure core (critical,
e.g. a desk standing in for a vault). See the [runbook](../runbooks/demo-day.md) for
setup and calibration.

## Act 0 — The problem (1 min, slide)

Plain geofences either miss intruders who carry no device, or alarm at every dog,
shadow and patrol. PIDS fuses geofence, camera, behaviour and passive identity into
one calibrated decision.

## Act 1 — The quiet perimeter (1 min)

- **Show:** the console on the projector, map of the room with both zones, the live
  camera panel (zones drawn on the image) and the naive-baseline counter at 0 / 0.
- **Narrator:** "Everything you see is live. The camera runs YOLO on this laptop's CPU
  at 20 ms a frame. Nothing is recorded."

## Act 2 — An authorised person walks in (2 min)

- **Badge holder** walks in from the door, across the floor, toward the camera corner.
- **Expect:**
  - A track appears.
  - Within a few seconds its sources show `ble:badge-team-1` and the identity reads
    authorised.
  - Its level stays nominal or elevated, with no alarm.
  - The naive counter goes up: a plain geofence would have alarmed on a colleague.
- **Narrator:** "Nobody tapped anything. The phone advertises a code that changes
  every 30 seconds. The system linked it to *this* person because the signal strength
  rose as she walked toward the scanner, and only hers did."

## Act 3 — An intruder slips in alongside (3 min)

- **Intruder** enters right next to the badge holder, and they walk together.
- **Expect:** while they walk side by side, *nobody* is whitelisted. The fusion panel
  shows no authorised-tag term on either track, because the badge cannot tell them
  apart.
- **Narrator:** "If in doubt, nobody is trusted. A missed intruder is the worst
  failure."
- They split up. The badge holder goes back to their desk, and the intruder heads for
  the secure core.
- **Expect:**
  - The badge stays with the badge holder.
  - The intruder goes ELEVATED → WARNING with a *predicted breach* (time-to-breach
    counts down), then CRITICAL on entering the core.
  - The console alarm sounds and the critical banner appears.
  - **The guard's phone buzzes.**
- **Narrator:** point at the fusion breakdown (why the score is what it is) and at the
  baseline counter.

## Act 4 — The response (2 min)

- **Guard** opens the alert on the phone, sees "what to do", the distance and
  direction, and taps **Acknowledge**.
- **Operator** clicks **Ask the agent**.
  - Claude reviews the evidence with read-only tools and recommends actions, citing the
    site procedures (SOP-01 §1).
  - The operator approves one recommendation. Nothing happens without that approval.
  - The incident report draft is ready to copy.
- **Operator** asks the log a question, e.g. "critical alerts in the secure core today".
  The answer shows how the question was understood.
- **Guard** resolves the alert on the phone.

## Act 5 — The evidence (2 min, slides + Grafana)

- **Evaluation** (`docs/evaluation/results.md`), on 160 held-out scenarios: PIDS
  detects 99.3% of intrusions against 100% for naive line-crossing, with 82% fewer
  nuisance alarms.
  - Ablations show identity tags cut nuisance alarms.
  - Ablations show breach prediction and the safety rails protect recall.
- **Edge** (`docs/evaluation/detector.md`): the ONNX export is lossless, 2.5× faster
  than PyTorch, and runs on the CPU only.
- **Grafana:** capture → decision latency is about 170 ms, against the 2 s budget.

## Optional — Outdoors with GPS (2 min)

A teammate carries the laptop's GPS module (`make gps`) or shares the guard app's
position outside. The cooperative tag appears on the map and links to the camera
track when in view.

## If something fails

| Failure | Do this |
|---|---|
| Camera won't open | Check macOS camera permission for the terminal app. Fall back to `pids-edge run --source clip.mp4` (a pre-recorded rehearsal). |
| Phone gets no alert | Check the phone and laptop are on the same Wi-Fi and the app's feed chip reads "open". The console alarm still shows the detection. |
| Badge not linking | Check Bluetooth permission on the laptop and that the app shows Badge: on. Have the badge holder walk toward and away from the laptop. |
| Agent unavailable | The panel says "agent is off". Alerting is unaffected; say so, it's by design. |
| Everything is confused after rehearsals | `make demo-reset` |
