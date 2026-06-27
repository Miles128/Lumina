"""Tests for GitHub trending fetch fallback."""

from __future__ import annotations

from unittest.mock import patch

from secretary.agent.github_trending_fetch import (
    _format_api_list,
    _parse_repos_from_html,
    fetch_github_trending,
    is_github_trending_url,
)


def test_is_github_trending_url() -> None:
    assert is_github_trending_url("https://github.com/trending?since=weekly")
    assert not is_github_trending_url("https://github.com/foo/bar")


def test_parse_repos_from_html() -> None:
    html = '<a href="/harry0703/MoneyPrinterTurbo">x</a>'
    repos = _parse_repos_from_html(html)
    assert repos == [("harry0703", "MoneyPrinterTurbo")]


def test_fetch_uses_search_api_when_html_empty() -> None:
    with patch(
        "secretary.agent.github_trending_fetch._fetch_html_trending",
        return_value=[],
    ):
        with patch(
            "secretary.agent.github_trending_fetch._fetch_search_api_trending",
            return_value=[
                {
                    "full_name": "foo/bar",
                    "stars": 1000,
                    "description": "demo",
                }
            ],
        ):
            out = fetch_github_trending("https://github.com/trending?since=weekly")
    assert "foo/bar" in out
    assert "Search API" in out


def test_format_api_list() -> None:
    text = _format_api_list(
        [{"full_name": "a/b", "stars": 10, "description": ""}],
        since="weekly",
        source="api",
    )
    assert "a/b" in text
