# ADR-0007: LLM agent with provider abstraction (Claude primary, Ollama fallback), human in the loop

- **Status:** Accepted
- **Date:** 2026-10-16
- **Requirements:** AIL-06, AIL-07, AIL-08

## Context

The agent triages events, retrieves SOPs and drafts incident reports. Restricted sites
are often air-gapped; an internet-only design would be unrealistic there.

## Decision

A small provider interface with two implementations: the Anthropic Claude API
(primary — best tool-calling quality) and a local Ollama model (offline fallback).
Embeddings for RAG are computed locally so retrieval works offline either way. The
agent has read-only tools; any action it recommends is a proposal an operator must
approve. The agent never sits on the alerting path — alerts fire without it.

## Consequences

Detection and alerting never depend on an LLM or the internet. Quality degrades
gracefully offline. Every agent action is attributable to a human approval.

## Implementation (2026-10-16)

- **Model:** Claude Opus 5.5 (`claude-opus-5-5`), adaptive thinking, explicit effort
  (`LLM_EFFORT`, default `high`). Server-side refusal fallback (`fallbacks: "default"`)
  is enabled. The stable system prompt is prompt-cached, tools are strict, and the
  final answer is constrained by a JSON schema (structured outputs).
- **Fallback:** Ollama (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`) runs the same contract when
  Claude is unreachable or unconfigured. With neither configured, the agent endpoints
  return 503 and the console says so. Alerting is unaffected.
- **Tools** (read-only): `get_alert`, `recent_alerts`, `entity_history`,
  `site_overview`, `search_procedures`. Citations the agent was not shown are dropped
  before storage.
- **Retrieval:** SOP sections from `config/sops/`, embedded locally (BAAI/bge-small-en,
  ONNX via fastembed, baked into the image), searched by pgvector cosine distance and
  PostgreSQL full text, then fused by reciprocal rank.
- **Event-log questions:** the model fills a fixed filter schema; the server clamps it,
  runs an ORM query and writes the answer itself. No model-written SQL.
- **Human in the loop:** each recommended action is approved or rejected individually
  by a named operator, and every decision is audited.
