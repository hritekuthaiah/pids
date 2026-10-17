# Changelog

## [1.1.0](https://github.com/hritekuthaiah/pids/compare/v1.0.0...v1.1.0) (2026-10-17)


### Features

* **console:** draw and edit zones on the live map ([231dd68](https://github.com/hritekuthaiah/pids/commit/231dd6825986a9b4984ed1105ec41d106bd74318))
* the system knows where each camera is looking ([4fd4086](https://github.com/hritekuthaiah/pids/commit/4fd40864ba381f07fd2179a9aa1cbde47aedf6d3))
* use a spare phone as the camera node ([ba21535](https://github.com/hritekuthaiah/pids/commit/ba21535a6f967bed92a212ee811b5a18458c21ad))


### Bug Fixes

* **dashboard:** give the test ResizeObserver stub the real signature (CodeQL) ([50ffef3](https://github.com/hritekuthaiah/pids/commit/50ffef306901c17dc154dc9318f19dee9eab5a05))


### Documentation

* CLAUDE.md for live zone editing, phone cameras and camera views ([ef84afa](https://github.com/hritekuthaiah/pids/commit/ef84afaa7e1b5116cd64c6719c8b8645a9b46ba0))

## 1.0.0 (2026-10-16)


### Features

* **api-client:** add generated, typed TypeScript client shared by both apps ([1f3613b](https://github.com/hritekuthaiah/pids/commit/1f3613b64448962abc91c346d854807d12377b2e)), closes [#7](https://github.com/hritekuthaiah/pids/issues/7)
* **core:** add calibrated fusion, threat scoring, alert FSM and decision engine ([3d3c517](https://github.com/hritekuthaiah/pids/commit/3d3c517e87396498a7a55ca188149a501384cea1))
* **core:** add interface contracts, site model and nested-zone geofencing ([9dea9b8](https://github.com/hritekuthaiah/pids/commit/9dea9b8f9ac821a6d6fcfc74db91670149f3c127))
* **core:** add Kalman forecaster, behavioural features and spoof monitor ([b9a1693](https://github.com/hritekuthaiah/pids/commit/b9a1693b94212b7cb153e947021f3fe085b5977a))
* **core:** add NodeHealth contract for edge liveness reports ([58c900a](https://github.com/hritekuthaiah/pids/commit/58c900a5ac6d48d4d6b42589917e3017b8ac936e))
* **core:** passive BLE badges — rolling ids and evidence-based linking ([c483a08](https://github.com/hritekuthaiah/pids/commit/c483a08608254b0696c44b16b99b289156b10673))
* **dashboard:** add the control-room console ([f8f8935](https://github.com/hritekuthaiah/pids/commit/f8f89351271b44894d513c636923e29ed3516a2c)), closes [#21](https://github.com/hritekuthaiah/pids/issues/21)
* **dashboard:** agent triage panel and plain-language log questions ([78636bf](https://github.com/hritekuthaiah/pids/commit/78636bf0319683d2c12d09208883eee4432619c2))
* **dashboard:** count naive-geofence alarms against PIDS alerts ([caf64ef](https://github.com/hritekuthaiah/pids/commit/caf64ef2a1f4c42127e44ff4affb5046a6146540))
* **dashboard:** embed the edge node's live camera preview ([2828934](https://github.com/hritekuthaiah/pids/commit/28289345e73254d5996325cd4ede413e9a7482e9))
* **dashboard:** place the camera and baseline panels under the map ([cd7fcb7](https://github.com/hritekuthaiah/pids/commit/cd7fcb7d0d8aadaecb0b295309dd41eade9472ff))
* **demo:** one-command demo, production console container, demo script ([3d03b2a](https://github.com/hritekuthaiah/pids/commit/3d03b2aca9fa118a619534f0bfec16f20c121ec6))
* **edge,server:** BLE badge scanner and the guard's badge-secret endpoint ([91b5559](https://github.com/hritekuthaiah/pids/commit/91b555917861d823d509c46b2670433424f08570))
* **edge:** camera perception pipeline — YOLO26 ONNX, ByteTrack, floor homography ([33472be](https://github.com/hritekuthaiah/pids/commit/33472be79e222dd8cd832d0ee0986a5038cdf5a0))
* **edge:** detector accuracy on COCO val and PyTorch/ONNX/INT8 benchmarks ([3adf123](https://github.com/hritekuthaiah/pids/commit/3adf123d64cbc005106f90b62de5086218dc48d0))
* **edge:** NMEA GPS driver with auto-detect, thermal heat confirmation ([03b5fc2](https://github.com/hritekuthaiah/pids/commit/03b5fc2f2fda1935f07c2b946568166648066708))
* **guard:** Android guard app — live alerts, passive BLE badge, GPS tag ([6152381](https://github.com/hritekuthaiah/pids/commit/6152381df066d4a153f60429b630aced4d9649a6))
* **ml:** evaluation harness — PIDS vs baselines with ablations and CIs ([25e32f7](https://github.com/hritekuthaiah/pids/commit/25e32f733adcab3f37ad3cd6073c467bf8bc938f))
* **ml:** train behaviour model and calibrate fusion with domain constraints ([ddf98c9](https://github.com/hritekuthaiah/pids/commit/ddf98c95856fed36346e9c651c0199a14d761690))
* **obs:** Prometheus + Grafana with a provisioned operations dashboard ([ed500ec](https://github.com/hritekuthaiah/pids/commit/ed500ec2fbb1d76314afa208ce5cdd8a0974277f))
* **security:** MQTT over TLS on 8883 with verified broker certificates ([c714176](https://github.com/hritekuthaiah/pids/commit/c7141767646abe27f75e8be8441c69792fff94b6))
* **server:** add MQTT decision service and durable notification worker ([2745aa7](https://github.com/hritekuthaiah/pids/commit/2745aa7216a5a9e620fd19f31cd1a9651c618359))
* **server:** add PostGIS schema, migrations, settings and admin seeding ([c9da6b6](https://github.com/hritekuthaiah/pids/commit/c9da6b68267da499409375f01e9dd5377a7e3bd3))
* **server:** add REST API with auth, RBAC, alert lifecycle and WebSocket gateway ([1c8a939](https://github.com/hritekuthaiah/pids/commit/1c8a939f2a29b84d7c77593f4e2f544e3ddcecdd))
* **server:** export OpenAPI with WebSocket message schemas for client codegen ([af11615](https://github.com/hritekuthaiah/pids/commit/af11615812ae56c14e1db15347e41c069874d90b)), closes [#7](https://github.com/hritekuthaiah/pids/issues/7)
* **server:** LLM agent layer — triage, procedure retrieval, log questions ([6aebd20](https://github.com/hritekuthaiah/pids/commit/6aebd20b572abb9ff4c0889ffb3ca7cc37009f31))
* **server:** run and list the configured live site first ([b52c62a](https://github.com/hritekuthaiah/pids/commit/b52c62afa94b507a63ff35b555e5c9220c31227d))
* **sim:** add labelled scenario simulator with realistic sensor models ([9866a69](https://github.com/hritekuthaiah/pids/commit/9866a693a5711bddd21dbf3cb7995adbe60fe245)), closes [#14](https://github.com/hritekuthaiah/pids/issues/14)
* **sim:** stream scenarios to MQTT in real time as simulated edge nodes ([f9adaaf](https://github.com/hritekuthaiah/pids/commit/f9adaaf383dd5c106a1ea32d55a57977f2cc9126)), closes [#14](https://github.com/hritekuthaiah/pids/issues/14)


### Bug Fixes

* **core:** harden identity association and gate evidence on detection quality ([819736b](https://github.com/hritekuthaiah/pids/commit/819736be6ff14134463e5b300e0ec672dddf9dcd))
* **core:** keep alert episodes unique across restarts and tracker-id reuse ([12b4bf1](https://github.com/hritekuthaiah/pids/commit/12b4bf17e1bf570482f1f6b06325cb46b0ec3350)), closes [#17](https://github.com/hritekuthaiah/pids/issues/17)
* **dashboard:** fit the console top bar in a 1280 px viewport ([9303d30](https://github.com/hritekuthaiah/pids/commit/9303d303947d8cee943cc0d4c494e488a6b27c28))
* **dashboard:** keep the "Control room" caption whole at 1280 px ([32efcb8](https://github.com/hritekuthaiah/pids/commit/32efcb8a6990c884efd259da55985d067cfdcb08))
* **edge:** no implicit string concatenation inside list literals (CodeQL) ([7473b71](https://github.com/hritekuthaiah/pids/commit/7473b718ce74e4bda3376e70e486cbee6cf72f19))
* **infra:** never pull the locally built server image in compose ([e2359cf](https://github.com/hritekuthaiah/pids/commit/e2359cf9e5070644e5016f170eef875839b5571e))
* **security:** pin TLS 1.2+ in every MQTT client context (CodeQL) ([b6978f3](https://github.com/hritekuthaiah/pids/commit/b6978f3406f2a9339c4d95abd7bd0b6b3a317769))
* **server:** blank values in .env mean unset (MQTT_CA_FILE, OLLAMA_BASE_URL) ([e7a11fa](https://github.com/hritekuthaiah/pids/commit/e7a11faea9f23ab65bf9b4f306adbe3663fc2fab))
* **server:** bootstrap a fresh stack and wait for a seeded site ([b7d32de](https://github.com/hritekuthaiah/pids/commit/b7d32de7224323249c21a5f1402a073fd0ac8251))


### Refactoring

* address CodeQL findings in core and simulator ([5c908ca](https://github.com/hritekuthaiah/pids/commit/5c908cadc3f1c662f94a2a48f9fdd65846b3e86c))
* address CodeQL findings in the server ([88185f9](https://github.com/hritekuthaiah/pids/commit/88185f9ffa0380247d05228ddc7e109dffcfc9e4))


### Documentation

* add requirements register, architecture overview, ADRs and roadmap ([e8b5851](https://github.com/hritekuthaiah/pids/commit/e8b585161fd7e477c8a5b4a4b8c17994ea09fa86))
* ADR-0011 edge perception pipeline; health topic in overview ([1b9c780](https://github.com/hritekuthaiah/pids/commit/1b9c78015604c8df5a5dd04b5eb50bb996e3b8e3))
* CLAUDE.md — edge node, demo-room site, M4 state and gotchas ([6edc28b](https://github.com/hritekuthaiah/pids/commit/6edc28b0052d00c7a62132ef60b595c6836e103a))
* record fusion calibration decision and first held-out results ([35f5679](https://github.com/hritekuthaiah/pids/commit/35f567936340cddb10c85bcc3fa92b5da80835b6)), closes [#28](https://github.com/hritekuthaiah/pids/issues/28)
* refresh agent notes with current architecture, decisions and gotchas ([d7f7f43](https://github.com/hritekuthaiah/pids/commit/d7f7f4318872f4d2b56ce338accab882e1b64304))
* v1.0 — README results and features, roadmap status, agent notes ([b001276](https://github.com/hritekuthaiah/pids/commit/b00127630fb5f7959cf1e941b4466d8a4d2633c2))


### Tests

* **dashboard:** add store, geometry, format and component tests ([faa36d3](https://github.com/hritekuthaiah/pids/commit/faa36d337564775998f68f9417e270067ce779f0)), closes [#21](https://github.com/hritekuthaiah/pids/issues/21)


### Build System

* **infra:** add PostGIS/pgvector, Redis and Mosquitto compose stack ([3008ff0](https://github.com/hritekuthaiah/pids/commit/3008ff03252a81a5c1c5f18273db2c28ad7b368f))
* **infra:** containerise the server and run it in the compose stack ([87d6d9d](https://github.com/hritekuthaiah/pids/commit/87d6d9d04b47a665ff406555462514e10e62fdff)), closes [#17](https://github.com/hritekuthaiah/pids/issues/17)
* initialise monorepo with uv workspace, toolchain pins and quality gates ([96f855c](https://github.com/hritekuthaiah/pids/commit/96f855c866e20e0c6d272d131d0b2d15350bb813))
* Update uv-build requirement from &lt;0.12,&gt;=0.11 to &gt;=0.11,&lt;0.14 ([f3adb77](https://github.com/hritekuthaiah/pids/commit/f3adb77b4e7fb3b09afdd797c2b65556c681d289))


### Continuous Integration

* add CI, CodeQL, secret scanning, release-please and dependabot ([8ef3118](https://github.com/hritekuthaiah/pids/commit/8ef3118d20bf642f047ac28dc1fc1b8ef6af9f65))
* add TypeScript job, CodeQL for TypeScript and npm dependency updates ([3cc4125](https://github.com/hritekuthaiah/pids/commit/3cc4125d6ce1f460b403a443210f06dad70acb70))
* boot the containerised stack and run integration tests on every PR ([ead3c2a](https://github.com/hritekuthaiah/pids/commit/ead3c2a2ad2146f17ae36f68c67827f28b7382ca))
* scan full history with pinned gitleaks CLI and tame bot updates ([75abc98](https://github.com/hritekuthaiah/pids/commit/75abc983ac550a4bfbdf58a00ff73807ca817105)), closes [#5](https://github.com/hritekuthaiah/pids/issues/5)
