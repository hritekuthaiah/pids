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
| `apps/server` (`pids_server`) | `pids-api` (FastAPI + WS), `pids-decision` (MQTT → engine), `pids-worker` (notifications), `pids-admin` |
| `packages/api-client` | Generated TS types (`openapi.json` → `schema.d.ts`) + typed client + live WS helper |
| `apps/dashboard` | React 19 + MapLibre control-room console |
| `apps/edge` (`pids_edge`) | Camera edge node: YOLO26n (ONNX Runtime) → ByteTrack → floor homography → MQTT, calibration tool, loopback MJPEG preview (ADR-0011) |
| `apps/guard` | *(M5)* Expo Android guard app |
| `config/sites/*.yaml` | Site geometry in local metres (single source of truth): `site-alpha` (simulated depot), `demo-room` (live demo) |
| `config/edge/` | Per-node edge config, floor marks and calibration |

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
PIDS_SITE_CONFIG=config/sites/demo-room.yaml make up-all   # make the demo room the live site
```

Demo logins are the `SEED_*` passwords in `.env` (never print them).

## Current state (16 Oct 2026)

- **Merged:** M0 foundation, M1 decision core + simulator + calibrated fusion
  (held-out: Pd 98.6 %, −82 % nuisance alarms vs naive line-crossing), M2 server
  platform, M3 dashboard, M4 camera pipeline (YOLO26n ~17 ms/frame on the laptop CPU,
  capture -> decision ~170 ms). Open: rest of M4 (GPS NMEA driver, BLE badge scanner,
  per-class detector eval #22, benchmarks #26), M5 guard app, M6 evaluation, M7 agent
  layer, M8 demo hardening.
- **Hardware in hand:** USB camera (plus the MacBook's built-in one), a GPS module (model
  and adapter still to be identified), Android phone(s). No Pi, thermal or RFID.
- **Whitelist decision (16 Oct):** *phones act as BLE badges* — authorised people's
  phones broadcast passively; scanners (the Mac's Bluetooth to start) hear them; identity
  is linked to camera tracks by position and RSSI-vs-motion correlation, with rolling IDs
  against replay. No purchase for now; ESP32 badges are the upgrade path. Write ADR-0012
  with the implementation. RFID tap-reads stay supported in code but are **not** used in
  the demo (tapping is not autonomous).
- **Demo plan:** live, not simulated — a room as the compound (camera high in a corner,
  floor tape for ground-plane calibration, zones taped on the floor), a badged teammate
  and an un-badged "intruder" walking in together, alerts to the guard phone, a naive
  baseline panel side by side; plus a short live outdoor GPS segment. Simulator and
  evaluation numbers are presented as evaluation, not as the live demo.

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
