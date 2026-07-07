"""Tests for agent-loop context compaction."""

from __future__ import annotations

from secretary.agent.context_compaction import (
    LOOP_CONTEXT_MAX_CHARS,
    compact_messages_if_needed,
    estimate_messages_chars,
)


def test_compact_messages_noop_when_small() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert compact_messages_if_needed(messages, None) == messages


def test_compact_messages_replaces_middle_history() -> None:
    messages = [{"role": "system", "content": "sys"}]
    for index in range(20):
        messages.append({"role": "user", "content": f"question {index} " + ("x" * 1200)})
        messages.append({"role": "assistant", "content": f"answer {index} " + ("y" * 1200)})
    before = estimate_messages_chars(messages)
    compacted = compact_messages_if_needed(messages, None, max_chars=LOOP_CONTEXT_MAX_CHARS, keep_tail=4)
    after = estimate_messages_chars(compacted)
    assert after < before
    assert any("[System] Earlier conversation was compacted" in str(item.get("content", "")) for item in compacted)
