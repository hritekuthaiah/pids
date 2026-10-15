# Security policy

PIDS is security software, so weaknesses in it matter more than usual.

## Reporting a vulnerability

Please **do not open a public issue.** Use GitHub's private
[security advisory form](https://github.com/hritekuthaiah/pids/security/advisories/new).
We aim to acknowledge reports within 72 hours.

## Scope

In scope: authentication/authorisation bypass, telemetry spoofing or injection,
MQTT ACL bypass, alert suppression, GPS-spoofing detection evasion, prompt injection
that makes the LLM agent act without operator approval, secrets exposure.

## Design commitments

- Telemetry is authenticated per device and confined by topic ACLs; TLS off localhost.
- No biometric data is processed ([ADR-0005](docs/adr/0005-tag-whitelisting-not-face-recognition.md)).
- The LLM agent has read-only tools and cannot execute actions without human approval
  ([ADR-0007](docs/adr/0007-llm-provider-abstraction.md)).
- Secrets live only in environment files that are git-ignored; CI and a pre-commit hook
  scan for leaked secrets.
