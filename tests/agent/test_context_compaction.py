"""Tests for agent-loop context compaction."""

from __future__ import annotations

from secretary.agent.context_compaction import (
    LOOP_CONTEXT_MAX_CHARS,
    CompactionResult,
    compact_messages_if_needed,
    estimate_messages_chars,
    estimate_messages_tokens,
)


def test_compact_messages_noop_when_small() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = compact_messages_if_needed(messages, None)
    assert isinstance(result, CompactionResult)
    assert result.messages == messages
    assert result.triggered is False
    assert result.mode == "none"


def test_compact_messages_replaces_middle_history_via_tokens() -> None:
    messages = [{"role": "system", "content": "sys"}]
    for index in range(20):
        messages.append({"role": "user", "content": f"question {index} " + ("x" * 1200)})
        messages.append({"role": "assistant", "content": f"answer {index} " + ("y" * 1200)})
    before = estimate_messages_tokens(messages)
    # Use a small budget to force compaction on the test fixture.
    result = compact_messages_if_needed(messages, None, max_tokens=8000, keep_tail=4)
    compacted = result.messages
    after = estimate_messages_tokens(compacted)
    assert result.triggered is True
    assert result.mode in {"rule_summary", "llm_summary", "truncate"}
    assert result.before_tokens >= before or result.before_tokens > 0
    assert after < before
    assert any(
        "[System] Earlier conversation was compacted" in str(item.get("content", ""))
        or "[System] Earlier context truncated" in str(item.get("content", ""))
        for item in compacted
    )


def test_compact_messages_backward_compat_max_chars() -> None:
    """Legacy max_chars parameter still works (converted to token budget)."""
    messages = [{"role": "system", "content": "sys"}]
    for index in range(20):
        messages.append({"role": "user", "content": f"question {index} " + ("x" * 1200)})
        messages.append({"role": "assistant", "content": f"answer {index} " + ("y" * 1200)})
    before = estimate_messages_chars(messages)
    result = compact_messages_if_needed(
        messages, None, max_chars=LOOP_CONTEXT_MAX_CHARS, keep_tail=4
    )
    after = estimate_messages_chars(result.messages)
    assert after < before


def test_estimate_tokens_smaller_than_chars() -> None:
    """Token estimate should be smaller than raw char count for normal text."""
    messages = [{"role": "user", "content": "hello world, this is a test message " * 10}]
    chars = estimate_messages_chars(messages)
    tokens = estimate_messages_tokens(messages)
    assert tokens < chars
    assert tokens > 0


def test_compaction_result_detail_json() -> None:
    result = CompactionResult(
        messages=[],
        triggered=True,
        mode="rule_summary",
        before_tokens=100,
        after_tokens=40,
        tool_results_cleared=2,
    )
    detail = result.to_detail()
    assert '"mode": "rule_summary"' in detail
    assert '"before_tokens": 100' in detail
