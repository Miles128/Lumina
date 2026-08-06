"""Tests for assembled-context snapshot builder (harness UI observability)."""

from __future__ import annotations

from secretary.agent.context_snapshot import build_context_snapshot
from secretary.agent.llm_client import LlmUsage


def test_build_context_snapshot_includes_full_message_text() -> None:
    messages = [
        {"role": "system", "content": "SOUL block " + ("x" * 400)},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    snap = build_context_snapshot(
        messages,
        trace_id="tr1",
        thread_id="th1",
        usage=LlmUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    assert snap["trace_id"] == "tr1"
    assert snap["thread_id"] == "th1"
    assert snap["message_count"] == 3
    assert snap["messages"][0]["role"] == "system"
    assert snap["messages"][0]["content"] == messages[0]["content"]
    assert snap["messages"][0]["index"] == 0
    assert snap["usage"]["prompt_tokens"] == 10
    assert snap["usage"]["total_tokens"] == 15
    assert snap["approx_total_tokens"] > 0
    assert "captured_at" in snap


def test_build_context_snapshot_serializes_tool_calls() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path":"a.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "file body"},
    ]
    snap = build_context_snapshot(messages, trace_id="t", thread_id="")
    assert "read" in snap["messages"][0]["content"]
    assert snap["messages"][1]["content"] == "file body"


def test_build_context_snapshot_includes_cache_and_compaction() -> None:
    usage = LlmUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_cache_hit_tokens=40,
        prompt_cache_miss_tokens=60,
    )
    snap = build_context_snapshot(
        [{"role": "user", "content": "x"}],
        usage=usage,
        compaction_before=200,
        compaction_after=100,
    )
    assert snap["usage"]["cache_hit_tokens"] == 40
    assert snap["usage"]["cache_miss_tokens"] == 60
    assert snap["compaction"]["before_tokens"] == 200
    assert snap["compaction"]["after_tokens"] == 100
