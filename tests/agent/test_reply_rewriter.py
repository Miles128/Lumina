"""Tests for LLM rewrite pass before safety sanitization."""

from __future__ import annotations

from secretary.agent.llm_config import LlmConfig
from secretary.agent.reply_rewriter import rewrite_if_forbidden_label


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
