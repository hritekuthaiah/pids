# PIDS — notes for coding agents

Autonomous Perimeter Intrusion Detection System: nested geofences + camera detection +
behavioural anomaly + cooperative-tag identity, fused into one calibrated threat
decision. Final-year major project (SVIT, BCS786); public portfolio repo. **Live demo:
27 Oct 2026.**

Read `docs/product/requirements.md` and `docs/architecture/overview.md` before
substantial work. Decisions in `docs/adr/` are locked; supersede them with a new ADR
rather than silently deviating.

## Non-negotiables

- **A missed intruder is the worst failure.** Thresholds are recall-biased; fusion and
  behaviour reduce nuisance alarms. Never trade detection for a quieter log.
- **No facial recognition**, ever — identity is cooperative tags (ADR-0005).
- **Identity is passive.** Whitelisted people never tap, scan or check in; they carry a
  tag the system reads on its own. A tag is granted to a camera track only when the match
  is unambiguous — if in doubt, nobody is whitelisted (recall first). Tags lower threat but
  never zero it, and are spoof-checked against the camera.
- CRITICAL requires a geometric breach of a critical/containment zone; the recall floor
  and containment rules sit outside the learned model (ADR-0009).
- Thermal is a heat-*confirmation* input; an unavailable channel is neutral, not negative.
- `packages/core` stays pure: no network, DB, filesystem or wall-clock access. Time is
  passed in. This is what makes the evaluation harness trustworthy.
- Models train on simulator seeds 0–999 only; evaluation uses seeds ≥ 10000. Fusion
  weights + thresholds ship together as `config/models/decision-model.json`.
- The LLM agent is off the alerting path and cannot act without operator approval.
- Edge target is ARM64 + ONNX Runtime — never TensorRT.
- Out of scope: acoustic detection, voice UI, cross-camera re-ID, federated learning.

## Repository map

| Path | What |
|------|------|
| `packages/core` (`pids_core`) | Contracts, geofence, Kalman, features, spoofing, fusion, scoring, alert FSM, `DecisionEngine`, naive baselines |
| `packages/sim` (`pids_sim`) | Labelled scenario simulator; `pids-sim` (offline compare) and `pids-sim live` (real-time MQTT) |
| `ml` (`pids_ml`) | Isolation Forest behaviour model, constrained fusion calibration, event-level comparison |
| `apps/server` (`pids_server`) | `pids-api` (FastAPI + WS), `pids-decision` (MQTT → engine), `pids-worker` (notifications), `pids-admin`; `agent/` = LLM triage, procedure retrieval, log questions (ADR-0007) |
| `packages/api-client` | Generated TS types (`openapi.json` → `schema.d.ts`) + typed client + live WS helper |
| `apps/dashboard` | React 19 + MapLibre control-room console; nginx image (`console` service) in production |
| `apps/edge` (`pids_edge`) | Camera edge node: YOLO26n (ONNX Runtime) → ByteTrack → floor homography → MQTT, calibration tool, loopback MJPEG preview (ADR-0011); the camera may be a USB/built-in device or a phone's MJPEG stream (ADR-0013) |
| `apps/guard` | Expo SDK 58 Android guard app; `modules/pids-badge` = Kotlin BLE badge advertiser, `modules/pids-camera` = Camera2 → MJPEG server so a spare phone *is* a camera node |
| `config/sites/*.yaml` | Site geometry in local metres (single source of truth): `site-alpha` (simulated depot), `demo-room` (live demo) |
| `config/edge/` | Per-node edge config, floor marks and calibration |
| `config/sops/` | Illustrative site procedures indexed for the agent |
| `infra/` | Postgres image, Mosquitto (+ TLS via `infra/certs`), Prometheus, Grafana |

## Commands

```bash
make setup            # once: .env with generated secrets, deps, git hooks
make up-all           # infra + api/decision/worker in Docker (self-migrates and seeds)
make sim-live         # real-time simulated edge nodes over MQTT (looping)
pnpm --filter @pids/dashboard dev   # dashboard on :5173 (proxies /api and /ws)
make check            # Python: ruff + mypy --strict + unit tests
make test-int         # integration tests on the running stack (isolated pids_test DB)
pnpm typecheck && pnpm lint && pnpm test && pnpm format:check   # TypeScript workspace
pnpm gen:api          # after any API/schema change — CI fails on stale types
make train            # behaviour model + decision model (~2 min)
make edge-model       # export YOLO26n to ONNX (isolated uvx env; PyTorch never enters the workspace)
make edge             # camera edge node against the stack; preview http://127.0.0.1:8090/stream.mjpg
make edge SOURCE=http://<phone-ip>:8081/stream.mjpg   # use a phone as the camera (ADR-0013)
make camera-test URL=http://<phone-ip>:8081/stream.mjpg   # check that stream before relying on it
PIDS_SITE_CONFIG=config/sites/demo-room.yaml make up-all   # make the demo room the live site
make demo / demo-reset   # live demo bring-up (LAN, TLS, console :8080) / clean slate between rehearsals
make site-export         # write the zones/origin drawn in the console back to config/sites/<live>.yaml (edge nodes read it)
make eval / edge-eval    # held-out evaluation report / detector accuracy + benchmarks
make obs / certs / env-sync   # Grafana :3000 / dev CA for MQTT TLS / add new .env.example keys
make gps-probe           # identify a plugged-in GPS module
```

Demo logins are the `SEED_*` passwords in `.env` (never print them).

## Current state (17 Oct 2026)

- **v1.0.0 released and tagged (17 Oct).** All milestones M0–M8 merged.
  - Decision core: held-out Pd 99.3% (139/140), 82% fewer nuisance alarms than
    naive line-crossing.
  - Camera edge node: YOLO26n ONNX, 20 ms/frame on the laptop CPU, lossless vs PyTorch.
  - GPS NMEA driver; passive BLE phone badges (ADR-0012).
  - Guard app.
  - Evaluation harness with ablations.
  - Agent layer (Claude Opus 5.5, Ollama fallback).
  - Observability.
  - MQTT TLS.
  - Demo kit.
- **Since v1.0.0 (all merged to `main`):**
  - **Live zone editing.** Operators draw and edit zones on the real basemap and save
    them without a restart — `PUT /api/v1/sites/{id}/geometry` (admin, audited)
    rewrites the stored SiteConfig and the PostGIS rows, `Site.reload` /
    `DecisionEngine.refresh_site` adopt them in place (tracks, alerts and badge links
    survive), and a `site_changed` WebSocket message makes every console refetch.
    Moving the site origin re-frames nodes, readers and features so they stay on the
    same ground, and rebuilds the engine (live tracks drop).
  - **Site location and typed coordinates.** In *Edit zones*, an admin can put the site
    on the real spot — **Use my location** (browser geolocation, with the fix accuracy
    shown), latitude/longitude boxes (a pasted `lat, lon` pair fills both), or *Pick on
    map* — and edit every corner of a zone as latitude/longitude, or paste a survey list
    to make a zone. Moving the origin *relocates* the whole site by default (zones,
    nodes, readers keep their size and layout); untick it to only re-anchor the frame.
    `make site-export` writes the result back to the site YAML.
  - **Phone as camera node (ADR-0013).** A spare Android phone's `pids-camera`
    foreground service streams MJPEG on the LAN; the edge node opens that URL exactly
    as it opens a webcam. No laptop webcam needed, nothing recorded on the phone, and
    no video reaches the server.
  - **The system knows where each camera looks.** Each node publishes a `NodeView` —
    the visible ground footprint in WGS84, the image→metres homography and the site
    origin — so the map draws the real footprint and clicking the live preview pins
    that pixel's position on the map.
- **Still needs a human:**
  - paste `ANTHROPIC_API_KEY` into `.env`
  - install the guard APK on phones (USB debugging)
  - Firebase/EAS accounts if remote push is wanted
  - measure the demo room and calibrate the camera on site
  - identify the GPS module (`make gps-probe`)
  - grant macOS camera and Bluetooth permission to the terminal
- **Demo plan:** [docs/demo/script.md](docs/demo/script.md). It is live, not
  simulated: a room as the compound, a badged teammate plus an intruder, alerts to
  the guard phone, the agent's triage, and the naive-baseline counter beside it.
- **Open stretch work:** #34 LSTM trajectories, #35 adaptive zones, #36 hosted demo.

## Map and zones

- Basemaps are keyless Esri raster tiles: dark, streets, satellite. Imagery stops around
  z19, so a room-sized site is deliberately over-scaled (`maxZoom: 23`, `fitBounds`
  capped at 21) — blurry is correct there, blank is a bug.
- Zone geometry is stored in **local metres** relative to the site origin; the API speaks
  **WGS84** in both directions. The editor sends rings as `[lon, lat]`, open (no repeated
  closing vertex): the server closes them.
- Zone edits are validated by `SiteConfig`, so the rules hold at runtime: ids unique, at
  least one critical zone, and no asset tag left pointing at a deleted containment zone
  (that check fires first — site-alpha's `crate-07` calls `armoury` home).
- Picking a new origin has two meanings, and `PUT .../geometry` takes both. By default
  (`relocate: true`) the site *moves*: the console carries every zone to the new origin at
  its real size (`translateRing`, WGS84 metres-per-degree) and the server keeps nodes,
  readers and features at the same local metres, so they travel with it. Without it
  (`relocate: false`) only the frame moves: zones stay on the ground they cover and the
  server converts nodes/readers/features so they stay put too. Either way the decision
  engine rebuilds and live tracks drop. A zone the console re-sends with no actions keeps
  the ones the site file gave it (the console has no editor for them).
- Zone and origin edits live in **PostGIS only**. `pids-admin seed` rewrites the site row
  from `config/sites/<site>.yaml` on every API start (`make up-all`, `make demo`), and the
  edge node reads that YAML for its origin: run `make site-export` after saving or the
  edit is lost on restart and the camera node disagrees with the console about where the
  site is. The console shows a node's footprint from its last `NodeView`, so after a
  relocation it stays at the old spot until the edge restarts on the exported file.
- A camera's drawn footprint is the `NodeView` it published (`GET /sites/{id}/views`),
  not the config's idealised sector: the edge node walks the image border, projects each
  sample onto the floor, steps down the column where a sample is at or beyond the
  horizon, and clips at the node's range. Both directions of the pixel↔ground mapping
  live in `apps/dashboard/src/lib/views.ts`; a click above the horizon says so rather
  than guessing.

## Conventions

- Python 3.12 (uv workspace), Node 24 + pnpm 10 (mise). TypeScript is pinned to 5.9:
  TS 7's native compiler has no JS API, which openapi-typescript and typescript-eslint need.
- Conventional Commits (hook-enforced). Branch → PR → green CI → rebase-merge. `main`
  requires the Python, TypeScript, infra-lint, secret-scan, full-stack and CodeQL checks
  plus resolved conversations (CodeQL posts review threads — fix the code, don't dismiss).
- In PR bodies write `Closes #a, Closes #b` — a bare `Closes #a, #b` closes only the first.
- Every PR references requirement IDs (AIL-xx / PLT-xx / NFR-xx).
- Timezone-aware UTC datetimes; ENU metres for kinematics, WGS84 for storage/maps.
- Secrets only in `.env` (git-ignored). Never print or commit them.

## Gotchas learned the hard way

- Commit `pyproject.toml` and `uv.lock` together: pre-commit stashes unstaged changes and
  the hooks run `uv run --frozen`, which fails on a mismatched lockfile.
- Live simulation must run in real time: the decision engine uses the wall clock, so
  accelerated playback makes everyone look fast (and spoofed).
- Tracker ids restart when an edge node restarts — prefix them with a per-boot nonce.
- Wire models set `json_schema_serialization_defaults_required=True`, so generated TS
  types mark defaulted fields as always present. Keep it on new models.
- MapLibre 6: named imports only; exclude it from Vite `optimizeDeps` (its worker URL
  breaks otherwise and GeoJSON layers silently vanish); size its container explicitly
  (its CSS forces `position: relative`). Basemaps must be keyless — CARTO now needs a key.
- Docker on macOS cannot reach USB cameras or serial GPS: the edge node runs natively
  on the demo laptop (ADR-0006). macOS asks camera permission for the *app* running the
  command (Terminal or Claude); until granted, OpenCV reports "not authorized".
- Export YOLO26 with `end2end=True`: the default ONNX export keeps the NMS-needing
  one-to-many head and is slower.
- The decision engine's constants (stitch gate, forecast horizon) were tuned at
  outdoor scale; check them at room scale before the demo.
- In non-interactive shells pnpm is not on PATH: use `mise exec -- pnpm ...`.
- The dashboard alarm is audible in the browser pane — silence it when testing.
- Pre-commit stashes *unstaged tracked* changes but leaves *untracked* files, so
  hooks can see half a change: commit a whole feature at once, or park untracked
  work outside the tree. A fresh git worktree needs `uv sync --all-packages` before
  hooks (mypy) run.
- pydantic turns `KEY=` into `Path('.')`; blank env values must map to `None`
  (`_blank_is_unset` in settings).
- nginx: a location-level `add_header` silently drops the server-level security
  headers; use `expires` for caching instead.
- aiomqtt leaks the socket on a refused TLS handshake (a ResourceWarning, and warnings
  are errors in tests); test negative TLS cases with `ssl` directly.
- The Expo template adds its own MIT `LICENSE` and `.claude/settings.json`; neither
  belongs here.
- Ultralytics `check_det_dataset("coco.yaml")` downloads all of COCO (18 GB);
  `make edge-eval` fetches only val2017.
- Benchmark latency on an idle machine (`--latency-only`); background builds
  inflate it 3-4×.
- `eslint-plugin-react-hooks` v7 enforces the compiler rules: no reading or writing a ref
  during render, and no `setState` inside an effect. Keep per-interaction state in a
  reducer and assign refs from an effect.
- `npx tsc --noEmit` inside `apps/dashboard` is not the same check as `pnpm typecheck`
  (`tsc -b`, project references): run the workspace one before pushing, or the console
  image build is where you find out.
- A new WS message needs three edits or the client union silently misses it:
  `schemas.py`, `export_openapi.py`'s `WS_MESSAGES`, and `ServerMessage` in the
  api-client.
- A new MQTT topic also needs a line in `infra/mosquitto/acl`. Without it the broker
  refuses the publish *silently*: the node logs a clean send and nothing ever arrives.
- Browser geolocation needs a secure context: it works on `http://localhost`, never on the
  LAN console (`http://192.168…:8080`). A laptop's fix is often ±20–100 m — fine to find
  the building, not the room's corner; use *Pick on map* on the satellite view for that.
- The `api` image bakes in `config/`, and `pids-admin` runs inside it: an edited site YAML
  reaches the database only after `make up-all` rebuilds the image (which re-seeds).
- OpenCV blocks forever on a dead network stream. Network sources get the FFMPEG
  backend with `rtsp_transport;tcp|stimeout;5000000`, open/read timeouts and a short
  retry limit — a phone that walks out of Wi-Fi must reconnect, not hang the pipeline.
- Camera2's `YUV_420_888` planes have row *and* pixel strides that differ by device;
  pack NV21 stride-aware or the phone's stream is a green smear on some hardware.
