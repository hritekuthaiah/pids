# Roadmap

Target: **v1.0 demo on 27 Oct 2026.** Each milestone ends in a demoable, committed,
CI-green state, so the project is presentable at every step. Progress is tracked as
GitHub milestones and issues; this page is the overview.

| Milestone | Scope | Requirements | Due |
|-----------|-------|--------------|-----|
| **M0 Foundation** | Monorepo, toolchain, Docker stack (PostGIS/pgvector, Redis, MQTT), CI, security scanning, docs, ADRs, project board | NFR-08 | 16 Oct |
| **M1 Decision core** | Contracts, coordinate frames, nested-zone geofencing, track features, Kalman forecast, spoofing checks, fusion, threat scoring, alert state machine, simulator | AIL-03 T1, AIL-05, AIL-09, AIL-15, PLT-10 | 17 Oct |
| **M2 Server** | Schema + migrations, auth/RBAC, zones/tags/alerts API, decision engine over MQTT, WebSocket gateway, notification dispatch | PLT-01–07, NFR-01, NFR-03 | 18 Oct |
| **M3 Dashboard** | Live map, alert queue + lifecycle, fusion explanation, incident review, zone management | PLT-08 | 20 Oct |
| **M4 Edge perception** | Camera + YOLO (ONNX) + ByteTrack + ground-plane projection, GPS NMEA driver, simulated thermal/RFID drivers, anomaly model, edge benchmarks | AIL-01, AIL-02, AIL-04, AIL-14 | 21 Oct |
| **M5 Guard app** | Android app: login, push alerts, alert detail, acknowledge, GPS tag sharing | PLT-09, PLT-06 | 22 Oct |
| **M6 Evaluation** | Baseline vs PIDS over thousands of simulated scenarios, ablations, latency, lead time; paper tables & figures | PLT-11, NFR-01, NFR-02 | 23 Oct |
| **M7 Agent layer** | Claude/Ollama triage agent with tools, RAG over SOPs, NL log query, incident reports, operator approval | AIL-06, AIL-07, AIL-08 | 24 Oct |
| **M8 v1.0** | Demo script, seed data, runbooks, hardening, release | — | 26 Oct |

**Stretch (only after M8):** trajectory Tier 2 (LSTM, AIL-03), adaptive zone suggestions
(AIL-16), MQTT TLS bridging to a hosted cloud instance (PLT-12).

## Definition of done (every milestone)

- Code merged to `main` through a PR with green CI (lint, strict types, tests, scans)
- Tests cover the new behaviour
- Docs/ADRs updated; requirement IDs referenced in the PR
- Demo path for the milestone verified end-to-end
