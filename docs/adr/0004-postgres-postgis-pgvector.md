# ADR-0004: PostgreSQL 17 + PostGIS + pgvector as the single store

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** PLT-01, PLT-05, AIL-07, AIL-08

## Context

We need spatial queries (zone membership, distance to boundary, spatial history),
an event/incident store, and vector search for RAG over SOP documents.

## Decision

One PostgreSQL 17 instance with PostGIS (zones as `geometry(Polygon, 4326)` with GiST
indexes) and pgvector (SOP chunk embeddings), built as our own multi-arch image from
the official Postgres image plus PGDG packages. Schema is owned by Alembic migrations.
The decision engine keeps an in-memory copy of zone geometry for its hot path and
refreshes it on change, so per-tick membership checks never wait on the database.

## Consequences

One operational database, transactional consistency between events and their
context, and native ARM64 images. A dedicated vector DB or time-series DB is not
needed at this scale; revisit if telemetry volume grows by orders of magnitude.
