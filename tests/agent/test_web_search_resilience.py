"""Tests for web search fallback, retry, and instant API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from secretary.agent import web_search
from secretary.agent.web_search import (
    _ENGINES,
    SearchResult,
    _ddg_instant,
    _fetch_html,
    fallback_engine_order,
    run_search,
)


def test_fallback_engine_order_chinese_query() -> None:
    with patch.object(web_search, "configured_api_engines", return_value=()):
        order = fallback_engine_order(None, "杭州 今天天气")
    assert order[:3] == ["bing", "baidu", "sogou"]


def test_fallback_engine_order_english_query() -> None:
    with patch.object(web_search, "configured_api_engines", return_value=()):
        order = fallback_engine_order(None, "OpenAI latest news")
    assert order[:2] == ["bing", "duckduckgo"]


def test_fetch_html_retries_on_transient_error() -> None:
    request = httpx.Request("GET", "https://example.com")
    fail = httpx.ConnectError("connection reset", request=request)
    ok_resp = MagicMock()
    ok_resp.text = "<html>ok</html>"
    ok_resp.raise_for_status = MagicMock()

    http = MagicMock()
    http.get.side_effect = [fail, ok_resp]
    client_cm = MagicMock()
    client_cm.__enter__.return_value = http

    with patch("secretary.agent.web_search.httpx.Client", return_value=client_cm):
        with patch("secretary.agent.web_search.time.sleep"):
            html = _fetch_html("GET", "https://example.com")
    assert html == "<html>ok</html>"
    assert http.get.call_count == 2


def test_ddg_instant_parses_json() -> None:
    payload = {
        "Heading": "杭州天气",
        "AbstractText": "今日晴，18°C。",
        "AbstractURL": "https://example.com/weather",
        "RelatedTopics": [
            {"Text": "Hangzhou - Wikipedia", "FirstURL": "https://en.wikipedia.org/wiki/Hangzhou"},
        ],
    }
    with patch("secretary.agent.web_search.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        response = client.get.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        results = _ddg_instant("杭州天气", 5)
    assert len(results) >= 2
    assert results[0].engine == "duckduckgo_instant"
    assert "18" in results[0].snippet


def test_run_search_uses_instant_when_html_engines_empty() -> None:
    def empty(_query: str, _limit: int) -> list[SearchResult]:
        return []

    instant_hit = [
        SearchResult(
            title="Weather",
            url="https://example.com/w",
            snippet="Sunny",
            engine="duckduckgo_instant",
        )
    ]
    with patch.object(web_search, "configured_api_engines", return_value=()):
        with patch.dict(_ENGINES, {name: empty for name in _ENGINES}):
            with patch.object(web_search, "_ddg_instant", return_value=instant_hit):
                results, engine = run_search("杭州天气", "auto", 3)
    assert engine == "duckduckgo_instant"
    assert results[0].title == "Weather"


def test_run_search_auto_unknown_engine_raises() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        run_search("test", "yahoo", 3)
