"""Tests for web/realtime query routing."""

from __future__ import annotations

from secretary.agent.web_routing import (
    WEATHER_ASK_LOCATION,
    build_weather_search_query,
    is_weather_request,
    is_web_search_query,
    resolve_weather_city,
    resolve_web_search,
)


def test_weather_without_city() -> None:
    assert is_weather_request("今天天气怎么样")
    assert resolve_weather_city("今天天气怎么样") is None


def test_weather_uses_location_city() -> None:
    assert resolve_weather_city("今天天气怎么样", location_city="杭州") == "杭州"


def test_weather_explicit_city_beats_location() -> None:
    assert resolve_weather_city("上海天气怎么样", location_city="杭州") == "上海"


def test_weather_with_city() -> None:
    assert resolve_weather_city("杭州天气怎么样") == "杭州"
    assert build_weather_search_query("杭州") == "杭州 今天天气 气温"


def test_weather_followup_city() -> None:
    history = [
        {"role": "user", "content": "今天天气怎么样"},
        {"role": "assistant", "content": WEATHER_ASK_LOCATION},
    ]
    assert resolve_weather_city("杭州", history) == "杭州"


def test_web_search_query_markers() -> None:
    assert is_web_search_query("搜一下 OpenAI 最新新闻")
    assert not is_web_search_query("你好")


def test_resolve_web_search_weather_needs_location() -> None:
    plan = resolve_web_search("今天天气怎么样")
    assert plan is not None
    assert plan.needs_location is True


def test_resolve_web_search_general_query() -> None:
    plan = resolve_web_search("搜一下 OpenAI 最新动态")
    assert plan is not None
    assert plan.needs_location is False
    assert plan.search_query == "搜一下 OpenAI 最新动态"
