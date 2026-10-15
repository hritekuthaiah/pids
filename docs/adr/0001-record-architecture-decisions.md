# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-16

## Context

PIDS is a team project that is examined in a viva and described in a journal
paper. Design choices will be questioned ("why not face recognition?", "why
Isolation Forest?", "why MQTT?") long after they were made.

## Decision

Significant decisions are recorded as short Architecture Decision Records in
`docs/adr/`, numbered sequentially, using `0000-template.md`. An ADR is never
edited after acceptance except to mark it superseded.

## Consequences

Every viva-defensible choice has a written rationale with its trade-offs. A PR that
changes a recorded decision must add a superseding ADR.
