# Requirements register

Consolidated from the project kickoff interview, the AI-layer PRD (v1.0) and the
IEEE paper draft. Every issue, PR and test should trace back to an ID here.

**Problem.** Restricted / border perimeters need security that keeps working when
nobody is watching. CCTV needs continuous human attention; GPS geofencing only
answers "inside or outside a polygon" with no notion of who the entity is, how it
moves, or how serious the event is.

**Objective.** Convert raw multi-sensor input into one trustworthy, graded threat
decision — and reduce nuisance alarms by reasoning about *behaviour*, not just
boundary crossings, **without** lowering the probability of detection.

**The single worst failure is a missed intruder.** Every threshold is biased toward
recall; fusion and behavioural reasoning are what keep the alarm rate usable.

**Deployment context.** Defence / military restricted zone. Two modes:
*exclusion* (keep unauthorised entities out) and *containment* (keep tagged assets
in). Entities: people on foot, vehicles, animals, and authorised personnel/assets
carrying cooperative tags. Users: a **guard** on an Android app and a
**control-room operator** on a web dashboard.

---

## 1. AI layer

Priority: **Must** = spine (system incomplete without it) · **Headline** ·
**Planned** (after the spine is frozen) · **Stretch** · **Skip** (future work).

| ID | Capability | Priority | Notes |
|----|-----------|----------|-------|
| AIL-01 | Vision detection — person / vehicle / animal (YOLO family) | Must | COCO-pretrained already covers all three classes; fine-tuning is an improvement, not a blocker. Animals matter: wildlife is a top nuisance-alarm source. |
| AIL-02 | Multi-object tracking (ByteTrack) | Must | Stable track IDs are the prerequisite for all behavioural analysis. |
| AIL-03 | Trajectory prediction → time-to-boundary early warning | Headline | Tier 1 Kalman (committed). Tier 2 LSTM only if it beats Tier 1 (ADE/FDE) on non-linear paths. |
| AIL-04 | Behavioural anomaly detection (Isolation Forest over per-track features) | Must | Features: speed, heading change, dwell, distance-to-boundary, curvature, time of day. Unsupervised: labelled intrusions are scarce. |
| AIL-05 | Threat scoring & graded severity | Must | Fused confidence × class × zone × whitelist → NOMINAL / ELEVATED / WARNING / CRITICAL. |
| AIL-06 | Agentic LLM triage + auto incident report | Planned | Tool-calling agent; **human-in-the-loop** for any action; runs off the edge. |
| AIL-07 | RAG over site SOP documents | Planned | Agent cites written procedure to justify recommendations. |
| AIL-08 | Natural-language event-log querying | Planned | Read-only, guard-railed. |
| AIL-09 | Decision-level sensor fusion → one calibrated confidence | Must | The intellectual core and the headline result. Inputs: geofence state, vision, tracking continuity, thermal presence, anomaly score, tag identity. |
| AIL-14 | Edge optimisation (ONNX Runtime; latency / FPS / size before & after) | Must (light) | NVIDIA TensorRT does not apply to Pi-class hardware. |
| AIL-15 | GPS-spoofing detection | Must | Physically implausible jumps/speeds, fix-quality anomalies, disagreement with vision. |
| AIL-16 | Adaptive geofences — learned zone *suggestions*, operator-approved | Stretch | System never changes a zone on its own. |
| AIL-02b | Cross-camera re-identification | Skip | Single-camera node. |
| AIL-10 | Acoustic detection | Skip | Not in the hardware plan. |
| AIL-11 | Voice interface | Skip | Low value. |
| AIL-12 | Face-recognition whitelisting | Skip — documented decision | Replaced by cooperative tags: privacy-by-design (ADR-0005). |
| AIL-13 | Federated / on-device training | Skip | Multi-node research scope. |

## 2. Platform

| ID | Requirement |
|----|-------------|
| PLT-01 | Nested zones (outer warning → inner critical, plus containment zones) stored in PostGIS; exclusion and containment modes; admin zone management. |
| PLT-02 | Registry of authorised cooperative tags (people, vehicles, assets) with validity windows and, for assets, a home containment zone. |
| PLT-03 | GPS ingestion from serial GPS modules (NMEA) and from guard phones. |
| PLT-04 | Realtime push of tracks, assessments and alerts to both clients over WebSockets. |
| PLT-05 | Alert lifecycle: open → acknowledged → resolved / false alarm, with debounce of repeats and immediate escalation; full incident log. |
| PLT-06 | Graded response channels: dashboard, mobile push, siren, email, SMS — behind one dispatch interface. Mobile push is real for the demo. |
| PLT-07 | Authentication and role-based access (admin, operator, guard); audit log of operator actions. |
| PLT-08 | Control-room web dashboard: live map, alert queue, fusion explanation, incident review. |
| PLT-09 | Guard Android app: push alerts, alert detail with map and instruction, acknowledge/resolve, share own position as a cooperative tag. |
| PLT-10 | Simulator producing labelled scenarios through the same contracts as real sensors; live (streaming) and offline (batch) modes. |
| PLT-11 | Evaluation harness: PIDS vs naive point-in-polygon baseline, with ablations, producing paper-ready tables and figures. |
| PLT-12 | Hosted demo environment that can be started for a demo and stopped afterwards. *(Stretch.)* |

## 3. Non-functional

| ID | Requirement |
|----|-------------|
| NFR-01 | **Latency:** breach → alert visible to users in **< 2 s** end-to-end; every hop timestamped and measured. |
| NFR-02 | **Recall first:** probability of detection must be ≥ baseline; nuisance-alarm reduction never bought with missed intrusions. |
| NFR-03 | **Security:** authenticated, encrypted telemetry (MQTT over TLS, per-device credentials, topic ACLs); authenticated API; secrets never in git; rate limiting; GPS-spoofing detection. |
| NFR-04 | **Privacy (India DPDP Act):** no biometric processing; data minimisation; raw imagery not stored by default; retention limits on location history; purpose limitation. |
| NFR-05 | **Reliability:** health-checked services; edge buffers telemetry across link loss; the stack recovers cleanly on restart. |
| NFR-06 | **Observability:** structured logs, metrics (incl. per-hop latency), dashboards. |
| NFR-07 | **Edge:** runs on ARM64 Pi-5-class hardware with ONNX Runtime; battery-powered sensor nodes; WiFi + 4G links. |
| NFR-08 | **Engineering quality:** strict typing, automated tests, CI-gated main branch, reproducible environments. |
| NFR-09 | **Honest scale claims:** hardware demo shows a small number of simultaneous entities; larger scale is characterised in simulation and reported separately. |

## 4. Success metrics

| Metric | Definition | Target |
|--------|-----------|--------|
| **NAR reduction** (primary) | Nuisance alarms per hour: naive baseline vs PIDS | Significant, quantified reduction |
| **Pd** | Fraction of true intrusions alerted | ≥ baseline |
| Detection latency | Breach → alert on client | < 2 s |
| Prediction lead time | Seconds of warning before the boundary is crossed | Reported |
| Detection quality | Per-class precision / recall / F1; mAP | Reported per class |
| Track stability | ID switches per track | Minimised |
| Anomaly lift | Precision/recall on anomalous tracks; lift on fused score | Positive |
| Trajectory Tier 2 | ADE / FDE vs Kalman on non-linear paths | Beats baseline |
| Edge performance | Latency, FPS, model size — before / after optimisation | Reported |
| Localisation error | Metres | Reported |

## 5. Constraints & current hardware

- Low-cost commodity hardware; cloud usage limited to demo windows.
- **In hand:** USB camera, serial GPS module, one Android phone.
- **Not yet in hand:** Raspberry Pi 5, MLX90640 thermal array, RFID/BLE reader. These are
  implemented as drivers behind the same interfaces with simulated sources, so the
  real devices drop in without changes upstream. The edge node runs on an ARM64
  laptop for the demo (same architecture as the Pi 5).
