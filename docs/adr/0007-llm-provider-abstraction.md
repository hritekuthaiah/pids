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
