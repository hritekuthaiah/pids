# PIDS — Autonomous Perimeter Intrusion Detection System

[![CI](https://github.com/hritekuthaiah/pids/actions/workflows/ci.yml/badge.svg)](https://github.com/hritekuthaiah/pids/actions/workflows/ci.yml)
[![CodeQL](https://github.com/hritekuthaiah/pids/actions/workflows/codeql.yml/badge.svg)](https://github.com/hritekuthaiah/pids/actions/workflows/codeql.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

Perimeter security for restricted and border sites that keeps working when nobody
is watching. PIDS combines **nested GPS geofences**, **computer vision**, **thermal
confirmation**, **behavioural anomaly detection** and **cooperative-tag identity**
into one calibrated threat decision — and reasons about *behaviour* to cut nuisance
alarms **without** lowering the probability of detection.

> **Status: v1.0** — every milestone of the [roadmap](docs/roadmap.md) is built, tested
> and documented; the live demo is on 27 Oct 2026 ([script](docs/demo/script.md)).

## Results

Held-out evaluation: 160 simulated scenarios (13.3 h) the models never saw during
training, with identical inputs for every engine. Full report, with 95 % intervals,
ablations and figures, in [docs/evaluation/results.md](docs/evaluation/results.md).

| Engine | Detects intrusions | Nuisance alarms / h |
|---|---|---|
| Traditional GPS geofencing | 14.3 % | 0 |
| Naive line-crossing over the same camera detections | 100 % | 185.5 |
| **PIDS** | **99.3 %** | **33.9 (−82 %)** |

On the edge, YOLO26n on ONNX Runtime matches PyTorch accuracy (0.397 vs 0.402 COCO
mAP) at 2.5× the speed: 20 ms per frame on a laptop CPU, no GPU
([detector.md](docs/evaluation/detector.md)). Capture → decision latency is ~170 ms,
against a 2 s budget.

![Architecture](docs/assets/pids-architecture.png)

## Why

- **CCTV** produces evidence but needs a human watching continuously; attention
  degrades over a shift.
- **GPS geofencing** is automatic but answers only "inside or outside?" — it cannot
  see an intruder without a device, tell a patrol from a trespasser, or grade an event.
- Turning sensitivity up to avoid missed intruders floods operators with false alarms
  until they stop trusting the system. **The real problem is holding a high
  probability of detection while keeping the nuisance-alarm rate low.**

## What it does

| | |
|---|---|
| **Nested zones** | Outer warning ring → inner critical core, plus containment zones for tagged assets. Exclusion *and* containment. |
| **Perception** | YOLO person / vehicle / animal detection + ByteTrack, projected onto the ground plane. |
| **Behaviour** | Isolation-Forest anomaly score over per-track movement features; Kalman time-to-boundary forecasts warn *before* a breach. |
| **Fusion** | Independent channels corroborate each other into one calibrated confidence — so no single noisy sensor raises an alarm on its own. |
| **Graded response** | NOMINAL → ELEVATED → WARNING → CRITICAL, pushed to a control-room dashboard and a guard's Android app. |
| **Identity without biometrics** | Never face recognition ([ADR-0005](docs/adr/0005-tag-whitelisting-not-face-recognition.md)). Guards' phones act as passive BLE badges with rolling ids. A badge is linked to a person only when its signal strength follows *their* movement, so nobody taps anything and an intruder walking beside a guard is not whitelisted ([ADR-0012](docs/adr/0012-passive-ble-badges.md)). GPS tags are spoof-checked against the cameras. |
| **Agentic triage** | Claude reviews an alert through read-only tools, cites the site's procedures and drafts the incident report. Every recommendation needs an operator's approval, and alerting never depends on it ([ADR-0007](docs/adr/0007-llm-provider-abstraction.md)). |
| **Secure by default** | Argon2id with rotating refresh tokens, RBAC and an audit log. Per-device MQTT credentials with topic ACLs, TLS on 8883 and verified broker certificates. Secrets live only in `.env`. |

## Quick start

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), [mise](https://mise.jdx.dev/)
(pins Node 24 + pnpm), GNU Make.

```bash
make setup     # .env with generated secrets, Python + JS deps, git hooks
make up-all    # Postgres/PostGIS/pgvector, Redis, MQTT, API, decision service, worker, console
make sim-live  # simulated edge nodes streaming a scenario — watch it on http://localhost:8080
make check     # lint + strict type-check + tests
```

Live demo: `make demo` (demo room, LAN, production console) and `make edge` (camera).
Observability: `make obs` (Grafana). `make help` lists every target.

## Repository layout

```
apps/
  server/      FastAPI API + WebSocket gateway, decision service, worker, LLM agent layer
  edge/        Camera edge node: YOLO26 (ONNX) + ByteTrack + floor homography, GPS, BLE badges
  dashboard/   Control-room console (React 19 + MapLibre), served by nginx in production
  guard/       Guard Android app (Expo SDK 58): alerts, passive BLE badge, GPS tag
packages/
  core/        Decision core: contracts, geofencing, Kalman, fusion, scoring, badges (pure, no I/O)
  sim/         Scenario simulator with labelled ground truth
  api-client/  Generated TypeScript types + client shared by both apps
ml/            Behaviour model, fusion calibration, evaluation harness
config/        Sites (local metres), edge nodes, models, site procedures
infra/         Postgres image, broker config + TLS, Prometheus, Grafana
docs/          Requirements, architecture, ADRs, evaluation, demo script, runbooks
```

## Documentation

- [Requirements register](docs/product/requirements.md) — every feature ID referenced in issues and PRs
- [Architecture overview](docs/architecture/overview.md) — components, messaging, latency budget, security
- [Architecture decision records](docs/adr/)
- [Evaluation results](docs/evaluation/results.md) · [Detector & edge benchmarks](docs/evaluation/detector.md)
- [Demo script](docs/demo/script.md) · [Demo-day runbook](docs/runbooks/demo-day.md)
- [Roadmap](docs/roadmap.md)
- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

## Team

Sai Vidya Institute of Technology, Bengaluru — Dept. of CSE, Major Project (BCS786), 2026-27.

- **Hritek Uthaiah M J** — integration lead; application, fusion & agent layer
- **Y Akhil** — perception, behavioural ML, geospatial, deployment
- **Dhanush V Kokare** — documentation & data
- **Abhishek K Chawan** — hardware & demo

Guide: **Prof. Arathi B N** · Co-guide: **Dr. Shashikumar D R**

## License

[AGPL-3.0-or-later](LICENSE) — see [ADR-0008](docs/adr/0008-license-agpl.md).
