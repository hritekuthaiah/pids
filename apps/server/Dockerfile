# syntax=docker/dockerfile:1.7
# PIDS server image — one image, three processes (pids-api / pids-decision / pids-worker).
# Build context: repository root (uv workspace).

FROM ghcr.io/astral-sh/uv:0.11.28-python3.12-trixie-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# 1) dependencies only — cached until a lockfile or manifest changes
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/README.md packages/core/
COPY packages/sim/pyproject.toml packages/sim/README.md packages/sim/
COPY ml/pyproject.toml ml/README.md ml/
COPY apps/server/pyproject.toml apps/server/README.md apps/server/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package pids-server

# 2) workspace sources
COPY packages/core packages/core
COPY packages/sim packages/sim
COPY ml/src ml/src
COPY apps/server apps/server
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package pids-server


FROM python:3.12-slim-trixie AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PIDS_ENV=prod
RUN groupadd --system --gid 10001 pids && useradd --system --uid 10001 --gid 10001 --home /app pids
WORKDIR /app
COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 apps/server/alembic.ini apps/server/alembic.ini
COPY --chown=10001:10001 apps/server/src/pids_server/db/migrations apps/server/src/pids_server/db/migrations
COPY --chown=10001:10001 config config
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]
CMD ["pids-api"]
