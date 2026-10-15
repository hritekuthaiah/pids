# ADR-0008: License the project under AGPL-3.0-or-later

- **Status:** Accepted
- **Date:** 2026-10-16

## Context

The repository is public as a portfolio piece. The detector training/export pipeline
uses Ultralytics YOLO, which is AGPL-3.0.

## Decision

License the whole repository AGPL-3.0-or-later, compatible with that dependency.

## Consequences

Anyone may use and modify the code; network-service deployments must publish their
modifications. A commercial fork would need a different detector or an Ultralytics
enterprise licence.
