# ADR-0002: One monorepo, uv for Python, pnpm for TypeScript

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** NFR-08

## Context

The system spans Python (decision core, server, edge, ML) and TypeScript (dashboard,
Android app). The perception→fusion interface contract (PRD §7.1) is the seam most
likely to break integration; it must be a single source of truth.

## Decision

A single repository with a **uv workspace** (Python 3.12) and a **pnpm workspace**
(Node 24 LTS, pinned with mise). Contracts are pydantic models in `pids_core`; JSON
Schema and the server's OpenAPI document are exported from them and TypeScript types
are generated, so both clients compile against the exact server types.

## Consequences

One PR can change a contract and every consumer at once; CI catches drift. Tooling
(ruff, mypy --strict, pytest, ESLint, TypeScript strict) is configured once at the
root. The cost is a slightly more involved initial setup, absorbed by `make setup`.
