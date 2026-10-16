"""Agent layer without network or database: provider loops, guard rails, chunking."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from pids_server.agent import query as nlq
from pids_server.agent.llm import AgentError, AgentResult, ClaudeProvider, OllamaProvider, ToolSpec
from pids_server.agent.procedures import load_sections, split_sections
from pids_server.agent.triage import output_schema, triage

ROOT = Path(__file__).resolve().parents[3]
TOOL = ToolSpec(
    "get_alert",
    "the alert",
    {
        "type": "object",
        "properties": {"alert_id": {"type": "string"}},
        "required": ["alert_id"],
        "additionalProperties": False,
    },
)

REPORT = {
    "summary": "An untagged person entered the secure core.",
    "verdict": "likely_intrusion",
    "confidence": 1.4,
    "likely_cause": "Unauthorised entry.",
    "recommended_actions": [
        {
            "action": "Dispatch the nearest guard.",
            "priority": "now",
            "rationale": "Core breach.",
            "procedure_ref": "sop-01-intrusion-response#1",
        },
        {
            "action": "Close the gate.",
            "priority": "soon",
            "rationale": "Contain.",
            "procedure_ref": "sop-99-invented#7",
        },
    ],
    "cited_procedures": ["sop-01-intrusion-response#1", "sop-99-invented#7"],
    "incident_report": "At 10:00 ...",
}


def _usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=80)


class FakeMessages:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        # snapshot: the loop mutates its message list after each call
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def fake_client(responses: list[SimpleNamespace]) -> tuple[Any, FakeMessages]:
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


# ---------------------------------------------------------------------------
# Claude provider loop
# ---------------------------------------------------------------------------


async def test_claude_loop_runs_tools_and_returns_schema_json() -> None:
    use = SimpleNamespace(type="tool_use", id="tu_1", name="get_alert", input={"alert_id": "a1"})
    thinking = SimpleNamespace(type="thinking", thinking="")
    final = SimpleNamespace(type="text", text=json.dumps({"ok": True}))
    client, msgs = fake_client(
        [
            SimpleNamespace(stop_reason="tool_use", content=[thinking, use], usage=_usage()),
            SimpleNamespace(stop_reason="end_turn", content=[final], usage=_usage()),
        ]
    )
    seen: list[tuple[str, dict[str, Any]]] = []

    async def run_tool(name: str, args: dict[str, Any]) -> str:
        seen.append((name, args))
        return '{"level": "critical"}'

    out = await ClaudeProvider(client, "claude-opus-5-5", "high").run(
        "sys", "task", [TOOL], run_tool, {"type": "object"}, 4
    )
    assert out.output == {"ok": True}
    assert seen == [("get_alert", {"alert_id": "a1"})]
    second = msgs.calls[1]
    # the full assistant turn (thinking included) is replayed, results in ONE user message
    assert second["messages"][1] == {"role": "assistant", "content": [thinking, use]}
    assert second["messages"][2]["content"][0]["tool_use_id"] == "tu_1"
    first = msgs.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert first["fallbacks"] == "default"
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][0]["strict"] is True
    assert out.cache_read_tokens == 160


async def test_claude_tool_failure_is_reported_to_the_model() -> None:
    use = SimpleNamespace(type="tool_use", id="tu_1", name="get_alert", input={"alert_id": "a1"})
    client, msgs = fake_client(
        [
            SimpleNamespace(stop_reason="tool_use", content=[use], usage=_usage()),
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="{}")],
                usage=_usage(),
            ),
        ]
    )

    async def boom(name: str, args: dict[str, Any]) -> str:
        raise LookupError("no such alert")

    await ClaudeProvider(client, "claude-opus-5-5", "high").run("s", "t", [TOOL], boom, {}, 4)
    result = msgs.calls[1]["messages"][2]["content"][0]
    assert result["is_error"] is True
    assert "no such alert" in result["content"]


@pytest.mark.parametrize(
    ("stop", "match"), [("refusal", "declined"), ("max_tokens", "output tokens")]
)
async def test_claude_refusal_and_truncation_are_errors_not_answers(stop: str, match: str) -> None:
    client, _ = fake_client([SimpleNamespace(stop_reason=stop, content=[], usage=_usage())])

    async def never(name: str, args: dict[str, Any]) -> str:
        raise AssertionError

    with pytest.raises(AgentError, match=match):
        await ClaudeProvider(client, "claude-opus-5-5", "high").run("s", "t", [TOOL], never, {}, 4)


async def test_claude_without_tools_sends_none() -> None:
    client, msgs = fake_client(
        [
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text='{"a": 1}')],
                usage=_usage(),
            )
        ]
    )

    async def never(name: str, args: dict[str, Any]) -> str:
        raise AssertionError

    await ClaudeProvider(client, "claude-opus-5-5", "high").run("s", "t", [], never, {}, 2)
    import anthropic

    assert msgs.calls[0]["tools"] is anthropic.omit


# ---------------------------------------------------------------------------
# Ollama provider loop
# ---------------------------------------------------------------------------


async def test_ollama_loop_with_tool_calls_then_structured_answer() -> None:
    replies = [
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "get_alert", "arguments": {"alert_id": "a1"}}}
                ],
            }
        },
        {"message": {"role": "assistant", "content": "done"}},
        {"message": {"role": "assistant", "content": json.dumps({"verdict": "x"})}},
    ]
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    provider = OllamaProvider(
        "http://ollama:11434", "qwen3:4b", transport=httpx.MockTransport(handler)
    )

    async def run_tool(name: str, args: dict[str, Any]) -> str:
        return '{"level": "warning"}'

    out = await provider.run("sys", "task", [TOOL], run_tool, {"type": "object"}, 4)
    assert out.output == {"verdict": "x"}
    assert bodies[0]["tools"][0]["function"]["name"] == "get_alert"
    assert bodies[1]["messages"][-1]["role"] == "tool"
    assert bodies[2]["format"] == {"type": "object"}  # final answer constrained to the schema


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


class Scripted:
    name = "scripted"
    model = "scripted-1"

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output

    async def run(
        self,
        system: str,
        task: str,
        tools: list[ToolSpec],
        call_tool: Any,
        output_schema: dict[str, Any],
        max_turns: int,
    ) -> AgentResult:
        return AgentResult(output=self.output, provider=self.name, model=self.model)


async def test_triage_drops_invented_citations_and_clamps_confidence() -> None:
    tools = SimpleNamespace(retrieved={"sop-01-intrusion-response#1"})
    report, _, _ = await triage(Scripted(REPORT), tools, "alert-1")  # type: ignore[arg-type]
    assert report.confidence == 1.0
    assert report.cited_procedures == ["sop-01-intrusion-response#1"]
    assert [a.procedure_ref for a in report.recommended_actions] == [
        "sop-01-intrusion-response#1",
        "",
    ]


def test_triage_schema_is_strict() -> None:
    schema = output_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_query_filters_are_clamped_and_unknown_zones_dropped() -> None:
    spec = nlq.clamp(
        {
            "intent": "list",
            "since_minutes": 999_999,
            "levels": ["critical"],
            "zone_ids": ["secure-core", "DROP TABLE alerts"],
            "entity_classes": [],
            "statuses": [],
            "tag_id": "",
            "track_lost_only": False,
            "limit": 5000,
        },
        {"secure-core", "room-warning"},
    )
    assert spec.since_minutes == 43_200
    assert spec.limit == 100
    assert spec.zone_ids == ["secure-core"]


def test_query_rejects_values_outside_the_schema() -> None:
    with pytest.raises(ValueError, match="levels"):
        nlq.clamp(
            {
                "intent": "list",
                "since_minutes": 60,
                "levels": ["apocalyptic"],
                "zone_ids": [],
                "entity_classes": [],
                "statuses": [],
                "tag_id": "",
                "track_lost_only": False,
                "limit": 5,
            },
            set(),
        )


# ---------------------------------------------------------------------------
# Procedures
# ---------------------------------------------------------------------------


def test_procedures_split_at_section_headings() -> None:
    doc = "# SOP-9 Test\n\nIntro text.\n\n## First\nDo   this.\nThen that.\n\n## Second\nAnother.\n"
    sections = split_sections("sop-9", doc)
    assert [s.id for s in sections] == ["sop-9#1", "sop-9#2"]
    assert sections[0].title == "SOP-9 Test"
    assert sections[0].body == "Do this. Then that."


def test_site_procedures_load_with_unique_ids() -> None:
    sections = load_sections(ROOT / "config" / "sops")
    ids = [s.id for s in sections]
    assert len(ids) >= 15
    assert len(ids) == len(set(ids))
    assert all(s.body for s in sections)
