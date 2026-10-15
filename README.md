# PIDS — Autonomous Perimeter Intrusion Detection System

[![CI](https://github.com/hritekuthaiah/pids/actions/workflows/ci.yml/badge.svg)](https://github.com/hritekuthaiah/pids/actions/workflows/ci.yml)
[![CodeQL](https://github.com/hritekuthaiah/pids/actions/workflows/codeql.yml/badge.svg)](https://github.com/hritekuthaiah/pids/actions/workflows/codeql.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

Perimeter security for restricted and border sites that keeps working when nobody
is watching. PIDS combines **nested GPS geofences**, **computer vision**, **thermal
confirmation**, **behavioural anomaly detection** and **cooperative-tag identity**
into one calibrated threat decision — and reasons about *behaviour* to cut nuisance
alarms **without** lowering the probability of detection.

> **Status:** under active development toward the v1.0 demo (27 Oct 2026).
> See the [roadmap](docs/roadmap.md) for what is done and what is next.

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
| **Identity without biometrics** | Cooperative RFID/BLE/GPS tags, never face recognition ([ADR-0005](docs/adr/0005-tag-whitelisting-not-face-recognition.md)). |
| **Agentic triage** | An LLM agent drafts incident reports and cites site SOPs; any action needs operator approval. |

## Quick start

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), [mise](https://mise.jdx.dev/)
(pins Node 24 + pnpm), GNU Make.

```bash
make setup   # .env with generated secrets, Python + JS deps, git hooks
make up      # Postgres/PostGIS/pgvector, Redis, MQTT — waits until healthy
make check   # lint + strict type-check + tests
```

`make help` lists every target.

## Repository layout

```
apps/
  server/      FastAPI API + WebSocket gateway, decision engine, worker
  edge/        Edge node: sensor drivers, detection, tracking, MQTT publisher
  dashboard/   Control-room web dashboard (React + TypeScript)
  guard/       Guard Android app (Expo / React Native)
packages/
  core/        Decision core: contracts, geofencing, fusion, scoring (pure, no I/O)
  sim/         Scenario simulator with labelled ground truth
  contracts/   Generated TypeScript types shared by both clients
ml/            Model training, edge benchmarks, evaluation harness, paper figures
infra/         Container images and broker config
docs/          Requirements, architecture, ADRs, runbooks
```

## Documentation

- [Requirements register](docs/product/requirements.md) — every feature ID referenced in issues and PRs
- [Architecture overview](docs/architecture/overview.md) — components, messaging, latency budget, security
- [Architecture decision records](docs/adr/)
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
