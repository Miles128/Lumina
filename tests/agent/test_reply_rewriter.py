"""Tests for LLM rewrite pass before safety sanitization."""

from __future__ import annotations

from secretary.agent.llm_config import LlmConfig
from secretary.agent.reply_rewriter import (
    prepare_user_facing_reply,
    rewrite_if_forbidden_label,
    rewrite_profanity_until_clean,
)
from secretary.agent.reply_safety import contains_profanity


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def test_rewriter_skips_when_label_absent() -> None:
    raw = "这句话很正常。"
    got = rewrite_if_forbidden_label(raw, "继续", _llm_config())
    assert got == raw


def test_rewriter_calls_llm_when_label_present(monkeypatch) -> None:
    def _fake_chat_completion(*args, **kwargs) -> str:
        return "你说得对，我来直接回答。"

    monkeypatch.setattr(
        "secretary.agent.reply_rewriter.chat_completion",
        _fake_chat_completion,
    )
    got = rewrite_if_forbidden_label("用户指令模糊", "继续", _llm_config())
    assert got == "你说得对，我来直接回答。"


def test_rewriter_uses_lite_prompt_for_simple_sentence(monkeypatch) -> None:
    captured_system: dict[str, str] = {}

    def _fake_chat_completion(_config, messages, **kwargs) -> str:
        captured_system["content"] = messages[0]["content"]
        return "你直接说要做什么，我来处理。"

    monkeypatch.setattr(
        "secretary.agent.reply_rewriter.chat_completion",
        _fake_chat_completion,
    )
    rewrite_if_forbidden_label("请根据用户问题给出结果。", "继续", _llm_config())
    assert "机器腔文本" in captured_system["content"]


def test_rewriter_uses_strong_prompt_for_meta_sentence(monkeypatch) -> None:
    captured_system: dict[str, str] = {}

    def _fake_chat_completion(_config, messages, **kwargs) -> str:
        captured_system["content"] = messages[0]["content"]
        return "你直接告诉我下一步，我马上处理。"

    monkeypatch.setattr(
        "secretary.agent.reply_rewriter.chat_completion",
        _fake_chat_completion,
    )
    rewrite_if_forbidden_label("用户指令模糊，需等待用户澄清。", "继续", _llm_config())
    assert "第三人称分析腔" in captured_system["content"]


def test_profanity_rewrite_loops_until_clean(monkeypatch) -> None:
    replies = iter(["我靠还是不对", "这个问题确实棘手，我换个说法。"])

    def _fake_chat_completion(*args, **kwargs) -> str:
        return next(replies)

    monkeypatch.setattr(
        "secretary.agent.reply_rewriter.chat_completion",
        _fake_chat_completion,
    )
    got = rewrite_profanity_until_clean("他妈的太离谱了", "继续", _llm_config())
    assert got == "这个问题确实棘手，我换个说法。"
    assert not contains_profanity(got)


def test_profanity_rewrite_skips_when_clean() -> None:
    raw = "这个方案很可靠，挂靠即可。"
    assert rewrite_profanity_until_clean(raw, "继续", _llm_config()) == raw


def test_prepare_runs_forbidden_rewrite_before_sanitize(monkeypatch) -> None:
    """Sanitize must not strip the forbidden label before the LLM rewrite runs."""
    calls: list[str] = []

    def _fake_chat_completion(_config, messages, **kwargs) -> str:
        calls.append(messages[0]["content"])
        return "你直接说要做什么，我来办。"

    monkeypatch.setattr(
        "secretary.agent.reply_rewriter.chat_completion",
        _fake_chat_completion,
    )
    got = prepare_user_facing_reply(
        "请根据用户问题给出结果。",
        "继续",
        _llm_config(),
    )
    assert calls, "forbidden-label LLM rewrite should run"
    assert "机器腔文本" in calls[0]
    assert "用户" not in got
    assert got == "你直接说要做什么，我来办。"


def test_prepare_rewrites_profanity_then_sanitizes(monkeypatch) -> None:
    def _fake_chat_completion(*args, **kwargs) -> str:
        return "这个问题确实棘手。"

    monkeypatch.setattr(
        "secretary.agent.reply_rewriter.chat_completion",
        _fake_chat_completion,
    )
    got = prepare_user_facing_reply("他妈的太离谱了", "继续", _llm_config())
    assert got == "这个问题确实棘手。"
    assert not contains_profanity(got)