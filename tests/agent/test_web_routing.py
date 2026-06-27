"""Tests for web/realtime query routing."""

from __future__ import annotations

from unittest.mock import patch

from secretary.agent.web_routing import (
    build_search_query,
    is_web_search_query,
    resolve_web_search,
)


def test_weather_is_web_search() -> None:
    assert is_web_search_query("今天天气怎么样")


def test_weather_with_location_enriches_query() -> None:
    query = build_search_query("今天天气怎么样", location_city="杭州")
    assert query == "杭州 今天天气 气温"


def test_weather_without_location_uses_raw_message() -> None:
    query = build_search_query("今天天气怎么样")
    assert query == "今天天气怎么样"


def test_weather_explicit_city_in_message() -> None:
    query = build_search_query("杭州天气怎么样", location_city="上海")
    assert query == "杭州 今天天气 气温"


def test_weather_followup_city() -> None:
    history = [
        {"role": "user", "content": "今天天气怎么样"},
        {"role": "assistant", "content": "请稍等"},
    ]
    assert build_search_query("杭州", history) == "杭州 今天天气 气温"


def test_web_search_query_markers() -> None:
    assert is_web_search_query("搜一下 OpenAI 最新新闻")
    assert not is_web_search_query("你好")


def test_strip_rhetorical_prefix_for_github_query() -> None:
    from secretary.agent.web_routing import build_search_query

    query = build_search_query("你会上网查这个信息吗？GitHub 最近一周最火的项目都有哪些？")
    assert "GitHub" in query
    assert "你会上网查" not in query


def test_local_path_lookup_is_not_web_search() -> None:
    assert not is_web_search_query("查一下 ~/Documents/My Projects/ 里有哪些项目")
    assert is_web_search_query("GitHub 最近一周最火的项目都有哪些？")


def test_resolve_web_search_never_blocks_on_missing_location() -> None:
    plan = resolve_web_search("今天天气怎么样")
    assert plan is not None
    assert plan.search_query == "今天天气怎么样"


def test_resolve_web_search_uses_coords() -> None:
    with patch(
        "secretary.services.geolocation.reverse_geocode_city",
        return_value="杭州",
    ):
        plan = resolve_web_search(
            "今天天气怎么样",
            location_lat=30.27,
            location_lng=120.15,
        )
    assert plan is not None
    assert plan.search_query == "杭州 今天天气 气温"


def test_general_web_search_no_city_suffix() -> None:
    plan = resolve_web_search("搜一下 OpenAI 最新动态", location_city="杭州")
    assert plan is not None
    assert plan.search_query == "搜一下 OpenAI 最新动态"
