# PIDS developer entry points. `make` (or `make help`) lists everything.
# Toolchain is pinned in mise.toml (Node, pnpm) and .python-version (uv).

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

COMPOSE := docker compose
UV      := uv run --frozen

##@ Setup

.PHONY: env
env: ## Create .env from .env.example with freshly generated secrets (never overwrites)
	@if [ -f .env ]; then echo ".env already exists — leaving it alone"; exit 0; fi
	@cp .env.example .env
	@while grep -q 'CHANGE_ME' .env; do \
	  perl -0pi -e "s/CHANGE_ME/$$(openssl rand -hex 24)/" .env; \
	done
	@echo "wrote .env with random secrets"

.PHONY: env-sync
env-sync: ## Add keys that are new in .env.example to an existing .env (fresh secrets; never overwrites)
	@touch .env
	@grep -E '^[A-Z_][A-Z0-9_]*=' .env.example | while IFS='=' read -r key value; do \
	  if ! grep -qE "^$$key=" .env; then \
	    if [ "$$value" = "CHANGE_ME" ]; then value=$$(openssl rand -hex 32); fi; \
	    printf '%s=%s\n' "$$key" "$$value" >> .env; echo "added $$key"; \
	  fi; \
	done

.PHONY: setup
setup: env ## One-time bootstrap: .env, Python + JS deps, git hooks
	uv sync --all-packages
	@if [ -f pnpm-workspace.yaml ]; then pnpm install; fi
	pre-commit install --install-hooks
	pre-commit install --hook-type commit-msg

##@ Stack

.PHONY: up
up: ## Start infrastructure (Postgres/PostGIS, Redis, MQTT) and wait until healthy
	$(COMPOSE) up -d --build --wait db redis mqtt

.PHONY: up-all
up-all: ## Start infrastructure + containerised API, decision service and worker
	$(COMPOSE) --profile app up -d --build --wait

.PHONY: dev-api
dev-api: ## Run the API natively with reload-free uvicorn (uses .env)
	set -a && . ./.env && set +a && $(UV) pids-api

.PHONY: dev-decision
dev-decision: ## Run the decision service natively
	set -a && . ./.env && set +a && $(UV) pids-decision

.PHONY: dev-worker
dev-worker: ## Run the notification worker natively
	set -a && . ./.env && set +a && $(UV) pids-worker

.PHONY: sim-live
sim-live: ## Stream simulated scenarios to MQTT in real time (loops): make sim-live f=intrusion-foot
	set -a && . ./.env && set +a && $(UV) pids-sim live --family $(or $(f),intrusion-foot) --loop

.PHONY: down
down: ## Stop the stack (keeps data volumes)
	$(COMPOSE) --profile app down

.PHONY: ps
ps: ## Show stack status
	$(COMPOSE) ps

.PHONY: logs
logs: ## Tail stack logs
	$(COMPOSE) logs -f --tail=100

.PHONY: psql
psql: ## Open a psql shell on the dev database
	$(COMPOSE) exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

.PHONY: nuke
nuke: ## Stop the stack AND delete all data volumes (asks first)
	@read -r -p "Delete all PIDS data volumes? [y/N] " ans; [ "$$ans" = "y" ]
	$(COMPOSE) down -v

##@ Database

.PHONY: migrate
migrate: ## Apply database migrations
	set -a && . ./.env && set +a && $(UV) alembic -c apps/server/alembic.ini upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="message"
	set -a && . ./.env && set +a && $(UV) alembic -c apps/server/alembic.ini revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Seed the demo site and demo users (passwords from .env)
	set -a && . ./.env && set +a && $(UV) pids-admin seed --site config/sites/site-alpha.yaml

##@ Quality

.PHONY: fmt
fmt: ## Auto-format Python
	$(UV) ruff format .
	$(UV) ruff check --fix .

.PHONY: lint
lint: ## Lint Python
	$(UV) ruff format --check .
	$(UV) ruff check .

.PHONY: typecheck
typecheck: ## Static type-check Python (mypy --strict)
	$(UV) mypy packages/core/src packages/sim/src ml/src apps/server/src apps/edge/src

.PHONY: test
test: ## Run unit tests (no infrastructure needed)
	$(UV) pytest -m "not integration"

.PHONY: test-int
test-int: ## Run integration tests against the running stack (make up first)
	set -a && . ./.env && set +a && $(UV) pytest -m integration

.PHONY: cov
cov: ## Run unit tests with coverage report
	$(UV) pytest -m "not integration" --cov --cov-report=term-missing --cov-report=xml

.PHONY: check
check: lint typecheck test ## Everything CI runs, locally

.PHONY: hooks
hooks: ## Run every pre-commit hook against the whole repo
	pre-commit run --all-files

##@ Models & evaluation

.PHONY: train
train: ## Train the anomaly model and refit the decision model (training seeds 0-999)
	$(UV) pids-train all -n 200

.PHONY: sim
sim: ## Quick PIDS-vs-baseline comparison on a few simulated scenarios
	$(UV) pids-sim -n 3

##@ Edge node (runs natively: Docker on macOS cannot reach USB cameras)

EDGE_CONFIG ?= config/edge/edge-01.yaml

.PHONY: edge-model
edge-model: ## Export the YOLO26n detector to ONNX (one-off, isolated env, ~2 min)
	apps/edge/scripts/export-model.sh

.PHONY: edge-cameras
edge-cameras: ## List camera indices the edge node can open
	$(UV) pids-edge cameras

.PHONY: gps-probe
gps-probe: ## Identify a plugged-in GPS module: port, baud, constellations, model text
	$(UV) pids-edge gps --probe

.PHONY: gps
gps: ## Stream the GPS module's fixes to MQTT (no camera), per sensors.gps in EDGE_CONFIG
	set -a && . ./.env && set +a && $(UV) pids-edge gps --config $(EDGE_CONFIG)

.PHONY: edge
edge: ## Run the camera edge node against the stack; preview at http://127.0.0.1:8090/stream.mjpg
	set -a && . ./.env && set +a && $(UV) pids-edge run --config $(EDGE_CONFIG)

##@ Help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n"} \
	  /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
