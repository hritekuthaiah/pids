# Runbook: local development and demo

## First time

```bash
make setup        # .env with generated secrets, deps, git hooks
make up           # Postgres/PostGIS/pgvector, Redis, MQTT
make migrate      # schema
make seed         # Site Alpha + demo accounts (passwords are in .env, SEED_*)
make train        # behaviour model + decision model (~2 min)
```

## Run the platform

Either containerised:

```bash
make up-all       # infra + api (:8000), decision service, worker
```

or natively, one terminal each (faster iteration):

```bash
make dev-api
make dev-decision
make dev-worker
```

API docs: http://localhost:8000/docs · metrics: :8000/metrics, :9101 (decision), :9102 (worker).

## Feed it data without hardware

```bash
make sim-live f=intrusion-foot     # streams scenarios over MQTT in real time, looping
```

Families: normal, intrusion-foot, intrusion-vehicle, probe, loiter, spoofed-tag,
cloned-tag, asset-theft. The decision service cannot tell these from real edge nodes.

## Tests

```bash
make check        # lint + strict types + unit tests (no infrastructure)
make test-int     # integration tests against the running stack (isolated pids_test DB)
```

## Reset

```bash
make down         # stop everything, keep data
make nuke         # stop and delete all volumes (asks first)
```
