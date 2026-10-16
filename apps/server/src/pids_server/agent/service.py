"""Provider construction from settings (ADR-0007)."""

from __future__ import annotations

from functools import lru_cache

import anthropic

from pids_server.agent.llm import ClaudeProvider, FallbackProvider, OllamaProvider, Provider
from pids_server.settings import Settings


@lru_cache(maxsize=4)
def _claude(key: str, model: str, effort: str) -> ClaudeProvider:
    client = anthropic.AsyncAnthropic(api_key=key, max_retries=2, timeout=120.0)
    return ClaudeProvider(client, model, effort)  # type: ignore[arg-type]


def provider_for(settings: Settings) -> Provider | None:
    """Claude when a key is configured (with Ollama behind it if set up), else Ollama, else None."""
    local = (
        OllamaProvider(settings.ollama_base_url, settings.ollama_model)
        if settings.ollama_base_url
        else None
    )
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key is not None:
        key = settings.anthropic_api_key.get_secret_value()
        if key:
            claude = _claude(key, settings.llm_model, settings.llm_effort)
            return FallbackProvider(claude, local) if local else claude
    return local
