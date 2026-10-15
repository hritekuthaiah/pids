# Contributing

## Workflow

1. **Every change starts from an issue** traced to a requirement ID
   ([requirements register](docs/product/requirements.md)).
2. Branch from `main`: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`.
3. Commit with [Conventional Commits](https://www.conventionalcommits.org/) — enforced by
   a `commit-msg` hook. Use a scope where it helps: `feat(core): add zone index`.
4. Open a PR using the template. CI must be green; `main` is protected.
5. Merge with **rebase** so the Conventional Commit history stays intact for
   release-please, which maintains `CHANGELOG.md` and the version.

## Local setup

```bash
make setup     # once
make up        # start infrastructure
make check     # what CI runs
make hooks     # every pre-commit hook over the whole repo
```

## Standards

- **Python:** 3.12, `ruff` (lint + format), `mypy --strict`, `pytest`. Timezone-aware
  datetimes only. No `print` — use structured logging.
- **TypeScript:** strict mode, ESLint, Prettier. Types for API payloads are generated,
  never hand-written.
- **Tests:** new behaviour comes with tests. Decision logic (`packages/core`) aims for
  near-complete branch coverage and uses property-based tests for geometry and fusion.
- **Design changes:** add or supersede an ADR in `docs/adr/`.
- **Never commit:** secrets, `.env`, model weights, raw footage, personal data.

## Labels

`type:` feature / bug / task / docs · `area:` core / sim / server / edge / dashboard /
guard / ml / infra / docs · `priority:` P0–P2 · `track:` A (perception) / B (decision & app)
