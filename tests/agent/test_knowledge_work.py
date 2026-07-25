"""Tests for knowledge-work appendices and retry predicates."""

from __future__ import annotations

from secretary.agent.knowledge_work import (
    OFFICE_RETRY_USER,
    RESEARCH_RETRY_USER,
    intent_system_appendix,
    should_retry_for_office,
    should_retry_for_research_intent,
)
from secretary.agent.task_intent import TaskIntent


def test_intent_appendices_are_nonempty_and_distinct() -> None:
    research = intent_system_appendix(TaskIntent.RESEARCH)
    writing = intent_system_appendix(TaskIntent.WRITING)
    office = intent_system_appendix(TaskIntent.OFFICE)
    assert research and writing and office
    assert research != writing != office
    assert intent_system_appendix(TaskIntent.NONE) == ""
    assert intent_system_appendix(TaskIntent.CODE) == ""


def test_research_retry_when_unsourced_claims() -> None:
    assert should_retry_for_research_intent(
        "调研一下 RAG 评测指标",
        "根据业界实践，常用指标有 recall 和 nDCG。",
        [],
    )
    assert not should_retry_for_research_intent(
        "调研一下 RAG 评测指标",
        "根据[^1] recall 常用。\n\n[^1]: example.com/rag",
        ["web_search"],
    )


def test_office_retry_without_document_read() -> None:
    assert should_retry_for_office(
        "总结这份 report.docx 的三点",
        "报告主要讲了增长、风险与下一步。",
        [],
    )
    assert not should_retry_for_office(
        "总结这份 report.docx 的三点",
        "三点：…",
        ["read_document"],
    )
    assert RESEARCH_RETRY_USER
    assert OFFICE_RETRY_USER
