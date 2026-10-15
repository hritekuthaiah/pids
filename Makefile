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

.PHONY: down
down: ## Stop the stack (keeps data volumes)
	$(COMPOSE) down

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
	$(UV) mypy packages/core/src packages/sim/src ml/src

.PHONY: test
test: ## Run unit tests
	$(UV) pytest

.PHONY: cov
cov: ## Run unit tests with coverage report
	$(UV) pytest --cov --cov-report=term-missing --cov-report=xml

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

##@ Help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n"} \
	  /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
