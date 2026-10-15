# ADR-0010: Authentication, sessions and realtime delivery

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** PLT-04, PLT-07, NFR-03

## Context

Three user roles (admin, operator, guard) on two clients (web dashboard, Android app)
need authenticated REST and push updates. Guard phones lose connectivity and stay
logged in for a shift; a stolen phone or token must be containable.

## Decision

- **Passwords:** Argon2id, re-hashed transparently when parameters change; constant-ish
  failure path (dummy hash) so timing does not reveal registered emails; login rate
  limited per IP in Redis; every login (and failure) audited.
- **Access tokens:** HS256 JWT, 15 min, carrying role and the guard's tag id; `typ`
  claim checked so other token types can never be used as access tokens.
- **Refresh tokens:** opaque, stored only as SHA-256 hashes, rotated on every use and
  grouped into families; presenting an already-rotated token revokes the whole family
  (token-theft detection). Logout revokes the family.
- **WebSockets:** clients exchange their access token for a one-time, 30-second ticket
  (Redis `GETDEL`), so no long-lived credential appears in a WebSocket URL or proxy log.
- **Fan-out:** one Redis pattern subscription per API process feeds an in-process hub.
  Live snapshots are droppable for a slow client; alert messages are not — a client too
  slow to receive alerts is disconnected (and reconnects to a fresh snapshot) rather than
  silently missing one.
- **RBAC:** enforced per route with dependencies; tag (whitelist) changes are admin-only
  and hot-reloaded into the decision engine via Redis.

## Consequences

Stateless request auth with fast revocation at the refresh boundary (≤ 15 min exposure
for a stolen access token). Redis becomes a dependency of authentication (rate limits,
tickets) — acceptable as it is already required for realtime delivery.
