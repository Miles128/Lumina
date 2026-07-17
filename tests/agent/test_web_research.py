"""Tests for generic web-research retry heuristics."""

from __future__ import annotations

from secretary.agent.web_research import (
    reply_claims_web_search,
    reply_punts_to_user_browsing,
    should_retry_for_web_research,
)


def test_reply_punts_detects_trending_links() -> None:
    reply = (
        "抱歉，没有榜单。建议你直接访问：\n"
        "https://github.com/trending\n"
        "https://github.com/search?o=desc&s=stars"
    )
    assert reply_punts_to_user_browsing(reply)


def test_should_retry_when_only_search_and_apology() -> None:
    msg = "GitHub 最近涨星最快的项目"
    reply = "抱歉，刚才的搜索结果没有直接给出榜单。"
    assert should_retry_for_web_research(msg, reply, ["web_search"])


def test_should_not_retry_after_web_fetch() -> None:
    msg = "GitHub 最近涨星最快的项目"
    reply = "1. foo/bar — 本周 +1000 stars"
    assert not should_retry_for_web_research(msg, reply, ["web_search", "web_fetch"])


# ---------------------------------------------------------------------------
# reply_claims_web_search — "stated intent without tool invocation" detector
# ---------------------------------------------------------------------------


def test_claims_web_search_detects_commitment_phrase() -> None:
    """LLM wrote '让我搜一下' without calling web tools → should detect."""
    assert reply_claims_web_search("好的，让我搜一下。", [])


def test_claims_web_search_detects_various_phrases() -> None:
    for phrase in (
        "我来查一下",
        "帮您搜",
        "搜索一下",
        "联网查",
        "先搜一下",
        # Open-ended wording that a fixed phrase list would miss:
        "好，我联网抓一下一手资料，给你带引用。",
        "我去找找看。",
        "帮你带引用。",
        "我去检索一下。",
        "我去上网看看。",
    ):
        assert reply_claims_web_search(phrase, []), f"should detect: {phrase}"


def test_claims_web_search_false_when_web_tool_already_used() -> None:
    """If web_search was already called, no need to inject again."""
    assert not reply_claims_web_search("让我搜一下", ["web_search"])
    assert not reply_claims_web_search("让我搜一下", ["web_fetch"])


def test_claims_web_search_false_for_normal_reply() -> None:
    """Normal answers without search commitment don't trigger."""
    assert not reply_claims_web_search("alva.ai 是一个投资平台。", [])
    assert not reply_claims_web_search("你好，有什么可以帮你的吗？", [])


def test_claims_web_search_false_for_long_reply() -> None:
    """Long replies (>200 chars) are likely real answers, not commitments."""
    long_reply = "让我搜一下" + "x" * 200
    assert not reply_claims_web_search(long_reply, [])


def test_claims_web_search_false_for_empty() -> None:
    assert not reply_claims_web_search("", [])
    assert not reply_claims_web_search("   ", [])
