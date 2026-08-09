"""Tests for knowledge-work task intent resolution."""

from __future__ import annotations

import pytest

from secretary.agent.agent_profile import AgentProfile, resolve_auto_profile
from secretary.agent.task_intent import (
    TaskIntent,
    has_persist_signal,
    resolve_task_intent,
)


@pytest.mark.parametrize(
    ("message", "intent", "profile"),
    [
        ("帮我写一篇关于本地 Agent 的短文", TaskIntent.WRITING, AgentProfile.BUILD),
        ("把上面保存到 ~/Notes/agent.md", TaskIntent.WRITING, AgentProfile.BUILD),
        ("调研一下 RAG 评测指标", TaskIntent.RESEARCH, AgentProfile.ASK),
        ("总结这份 report.docx 的三点", TaskIntent.OFFICE, AgentProfile.ASK),
        ("把纪要写入 minutes.md", TaskIntent.OFFICE, AgentProfile.BUILD),
        ("重构 loop.py", TaskIntent.CODE, AgentProfile.BUILD),
    ],
)
def test_acceptance_intent_and_auto_profile(
    message: str, intent: TaskIntent, profile: AgentProfile
) -> None:
    assert resolve_task_intent(message) is intent
    assert resolve_auto_profile(message) is profile


def test_persist_signal_requires_target() -> None:
    assert has_persist_signal("把上面保存到 ~/Notes/agent.md")
    assert has_persist_signal("把纪要写入 minutes.md")
    assert not has_persist_signal("帮我写一篇短文")
    assert not has_persist_signal("写入记忆：喜欢咖啡")


def test_rewrite_is_writing_build() -> None:
    msg = "请润色并改写这段介绍"
    assert resolve_task_intent(msg) is TaskIntent.WRITING
    assert resolve_auto_profile(msg) is AgentProfile.BUILD


def test_research_plus_write_report_prefers_research_ask() -> None:
    msg = "调研一下本地 Agent 并写一份报告"
    assert resolve_task_intent(msg) is TaskIntent.RESEARCH
    assert resolve_auto_profile(msg) is AgentProfile.ASK


def test_summarize_path_docx_is_ask_not_filesystem_build() -> None:
    msg = "总结一下 ~/Documents/report.docx 的要点"
    assert resolve_task_intent(msg) is TaskIntent.OFFICE
    assert resolve_auto_profile(msg, filesystem_turn=True) is AgentProfile.ASK
