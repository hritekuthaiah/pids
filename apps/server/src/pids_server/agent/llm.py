"""LLM providers behind one interface (ADR-0007): Claude primary, Ollama offline fallback.

Both run the same agent contract: a system prompt, a task, read-only tools executed by
the caller, and a final answer constrained to a JSON schema. Each provider owns its own
tool loop because the wire formats differ; neither ever executes anything but the tools
it is handed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anthropic
import httpx

log = logging.getLogger("pids_server.agent")

ToolRunner = Callable[[str, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (object, additionalProperties false)


@dataclass
class AgentResult:
    output: dict[str, Any]
    provider: str
    model: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class AgentError(RuntimeError):
    """The model could not produce a usable answer (refusal, limit, malformed output)."""


class Provider(Protocol):
    name: str
    model: str

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: ToolRunner,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        """Run the tool loop to a final, schema-valid JSON answer."""


# ---------------------------------------------------------------------------
# Claude (Anthropic API)
# ---------------------------------------------------------------------------


class ClaudeProvider:
    name = "anthropic"

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        effort: Literal["low", "medium", "high", "xhigh", "max"],
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: ToolRunner,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        wire_tools: list[Any] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
                "strict": True,
            }
            for t in tools
        ]
        messages: list[Any] = [{"role": "user", "content": task}]
        result = AgentResult(output={}, provider=self.name, model=self.model)
        for _ in range(max_turns):
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                # Stable prefix (tools + system) cached across triages; adaptive thinking.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=wire_tools if wire_tools else anthropic.omit,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": output_schema},
                },
                # On a safety decline, the API retries on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            usage = response.usage
            result.input_tokens += usage.input_tokens
            result.output_tokens += usage.output_tokens
            result.cache_read_tokens += usage.cache_read_input_tokens or 0
            if response.stop_reason == "refusal":
                raise AgentError("the model declined this request")
            if response.stop_reason == "max_tokens":
                raise AgentError("the model ran out of output tokens")
            # Append the full assistant turn (thinking blocks included): append-only history.
            messages.append({"role": "assistant", "content": response.content})
            uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason == "tool_use" and uses:
                results: list[dict[str, Any]] = []
                for use in uses:  # all results go back in ONE user message
                    try:
                        content = await call_tool(use.name, dict(use.input))
                        results.append(
                            {"type": "tool_result", "tool_use_id": use.id, "content": content}
                        )
                    except (
                        Exception
                    ) as exc:  # report the failure to the model, don't crash the loop
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": use.id,
                                "content": f"Error: {exc}",
                                "is_error": True,
                            }
                        )
                    result.tool_calls.append({"tool": use.name, "input": dict(use.input)})
                messages.append({"role": "user", "content": results})
                continue
            text = "".join(b.text for b in response.content if b.type == "text")
            try:
                result.output = json.loads(text)
            except json.JSONDecodeError as exc:
                raise AgentError("the model's answer was not valid JSON") from exc
            return result
        raise AgentError(f"no answer within {max_turns} turns")


# ---------------------------------------------------------------------------
# Ollama (local, offline)
# ---------------------------------------------------------------------------


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self._transport = transport  # tests inject a mock transport

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: ToolRunner,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        wire_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        result = AgentResult(output={}, provider=self.name, model=self.model)
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as http:
            for turn in range(max_turns):
                last = turn == max_turns - 1 or not wire_tools
                body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
                if not last:
                    body["tools"] = wire_tools
                else:  # final turn: no tools, answer in the schema
                    body["format"] = output_schema
                r = await http.post(f"{self.base_url}/api/chat", json=body)
                r.raise_for_status()
                data = r.json()
                msg = data.get("message", {})
                result.input_tokens += int(data.get("prompt_eval_count", 0))
                result.output_tokens += int(data.get("eval_count", 0))
                calls = msg.get("tool_calls") or []
                messages.append(msg)
                if calls and not last:
                    for call in calls:
                        fn = call.get("function", {})
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            args = json.loads(args or "{}")
                        try:
                            content = await call_tool(fn.get("name", ""), args)
                        except Exception as exc:
                            content = f"Error: {exc}"
                        messages.append(
                            {"role": "tool", "content": content, "tool_name": fn.get("name", "")}
                        )
                        result.tool_calls.append({"tool": fn.get("name"), "input": args})
                    continue
                if "format" not in body:  # it answered without tools: ask for the schema now
                    messages.append(
                        {
                            "role": "user",
                            "content": "Now give your final answer as JSON in the required format.",
                        }
                    )
                    body = {
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "format": output_schema,
                    }
                    r = await http.post(f"{self.base_url}/api/chat", json=body)
                    r.raise_for_status()
                    msg = r.json().get("message", {})
                try:
                    result.output = json.loads(msg.get("content", ""))
                except json.JSONDecodeError as exc:
                    raise AgentError("the local model's answer was not valid JSON") from exc
                return result
        raise AgentError(f"no answer within {max_turns} turns")


# ---------------------------------------------------------------------------
# Selection and fallback
# ---------------------------------------------------------------------------


class FallbackProvider:
    """Claude first; if it is unreachable (network, outage, no key), the local model."""

    def __init__(self, primary: Provider, fallback: Provider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.model = primary.model

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: ToolRunner,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        try:
            return await self.primary.run(system, task, tools, call_tool, output_schema, max_turns)
        except (
            anthropic.APIConnectionError,
            anthropic.AuthenticationError,
            anthropic.InternalServerError,
        ) as exc:
            log.warning(
                "primary LLM unavailable (%s); using %s", type(exc).__name__, self.fallback.name
            )
            return await self.fallback.run(system, task, tools, call_tool, output_schema, max_turns)
