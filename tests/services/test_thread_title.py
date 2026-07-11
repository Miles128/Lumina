"""Tests for automatic chat thread titles."""

from __future__ import annotations

from unittest.mock import patch

from secretary.agent.llm_config import LlmConfig
from secretary.services.thread_title import (
    heuristic_title,
    sanitize_title,
    should_refresh_title,
    summarize_thread_title,
    user_turn_count,
)


def _cfg() -> LlmConfig:
    return LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="env",
    )


def test_heuristic_title_truncates() -> None:
    assert heuristic_title("短标题") == "短标题"
    long = "这是一段非常非常非常长的用户输入用来当标题"
    title = heuristic_title(long, max_chars=10)
    assert len(title) <= 10
    assert title.endswith("…")


def test_should_refresh_at_milestones() -> None:
    assert should_refresh_title(user_turns=1, last_auto_title_turn=0) is True
    assert should_refresh_title(user_turns=1, last_auto_title_turn=1) is False
    assert should_refresh_title(user_turns=2, last_auto_title_turn=1) is False
    assert should_refresh_title(user_turns=3, last_auto_title_turn=1) is True
    assert should_refresh_title(user_turns=6, last_auto_title_turn=3) is True


def test_user_turn_count() -> None:
    messages = [
        {"role": "user", "text": "a"},
        {"role": "assistant", "text": "b"},
        {"role": "user", "text": "c"},
    ]
    assert user_turn_count(messages) == 2


def test_sanitize_title_strips_quotes_and_about() -> None:
    assert sanitize_title("「飞书日程同步」") == "飞书日程同步"
    assert sanitize_title("关于 周末出行计划。") == "周末出行计划"


def test_summarize_thread_title_uses_llm() -> None:
    messages = [
        {"role": "user", "text": "帮我看看下周飞书有哪些会"},
        {"role": "assistant", "text": "下周有三场会议……"},
        {"role": "user", "text": "把周会改到周三"},
        {"role": "assistant", "text": "已记下改期请求"},
    ]
    with patch(
        "secretary.services.thread_title.chat_completion",
        return_value="飞书周会改期",
    ) as mocked:
        title = summarize_thread_title(messages, _cfg())
    assert title == "飞书周会改期"
    assert mocked.call_count == 1


def test_summarize_falls_back_when_llm_unavailable() -> None:
    messages = [{"role": "user", "text": "查一下本地项目目录"}]
    with patch(
        "secretary.services.thread_title.chat_completion",
        side_effect=RuntimeError("down"),
    ):
        title = summarize_thread_title(messages, _cfg())
    assert title == "查一下本地项目目录"
