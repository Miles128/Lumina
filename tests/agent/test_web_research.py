"""Tests for generic web-research retry heuristics."""

from __future__ import annotations

from secretary.agent.web_research import (
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
