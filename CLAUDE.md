# PIDS — notes for coding agents

Read `docs/product/requirements.md` and `docs/architecture/overview.md` before
substantial work. Decisions in `docs/adr/` are locked; supersede them with a new
ADR rather than silently deviating.

## Non-negotiables

- **A missed intruder is the worst failure.** Thresholds are recall-biased; fusion and
  behaviour reduce nuisance alarms. Never trade detection for a quieter log.
- **No facial recognition**, ever — identity is cooperative tags (ADR-0005).
- Thermal is a heat-*confirmation* input to fusion, not a classifier.
- `packages/core` stays pure: no network, DB, filesystem or wall-clock access. Time is
  passed in. This is what makes the evaluation harness trustworthy.
- The LLM agent is off the alerting path and cannot act without operator approval.
- Edge target is ARM64 + ONNX Runtime — never TensorRT.
- Out of scope: acoustic detection, voice UI, cross-camera re-ID, federated learning.

## Conventions

- Python 3.12 via uv workspace; `make check` = ruff + mypy --strict + pytest.
- Conventional Commits (hook-enforced). Branch → PR → green CI → rebase-merge.
- Timezone-aware UTC datetimes; ENU metres for kinematics, WGS84 for storage/maps.
- Every PR references requirement IDs (AIL-xx / PLT-xx / NFR-xx).
- Secrets only in `.env` (git-ignored). Never print or commit them.
