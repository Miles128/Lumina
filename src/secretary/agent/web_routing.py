"""Route realtime / web queries to web_search instead of tool-less direct chat."""

from __future__ import annotations

import re
from dataclasses import dataclass

WEATHER_ASK_LOCATION = (
    "无法获取你的位置。要查实时天气，请告诉我你在哪个城市（例如：杭州、上海），"
    "或在设置 → 外观中开启位置权限。"
)

_WEATHER_MARKERS = (
    "天气",
    "气温",
    "温度",
    "下雨",
    "下雪",
    "降雪",
    "降雨",
    "forecast",
    "weather",
)

_WEB_SEARCH_MARKERS = (
    "搜一下",
    "搜索一下",
    "查一下",
    "帮我搜",
    "帮我查",
    "联网",
    "网上",
    "百度",
    "谷歌",
    "最新新闻",
    "今日头条",
    "热点",
    "股价",
    "汇率",
    "实时",
    "现在多少",
    "多少钱",
    "news",
    "search for",
)

_NON_CITY_PREFIXES = frozenset(
    {"今天", "明天", "后天", "本地", "当地", "现在", "这边", "这里", "最近"}
)

_CITY_WEATHER_RE = re.compile(r"([\u4e00-\u9fffA-Za-z·]{2,12}?)天气")

_CITY_ONLY = re.compile(r"^[\u4e00-\u9fffA-Za-z·]{2,12}市?$")


def is_weather_request(text: str, history: list[dict[str, str]] | None = None) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if any(marker in cleaned or marker in lowered for marker in _WEATHER_MARKERS):
        return True
    if resolve_weather_city(cleaned, history):
        return True
    return False


def resolve_weather_city(
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    location_city: str | None = None,
) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    match = _CITY_WEATHER_RE.search(cleaned)
    if match:
        city = match.group(1).strip().strip("的")
        if city and city not in _NON_CITY_PREFIXES:
            return city.rstrip("市")
    if history and _recently_asked_weather_location(history):
        if _CITY_ONLY.fullmatch(cleaned):
            return cleaned.rstrip("市")
    if location_city:
        city = location_city.strip().rstrip("市")
        if city:
            return city
    return None


def build_weather_search_query(city: str) -> str:
    name = city.strip().rstrip("市")
    return f"{name} 今天天气 气温"


def is_web_search_query(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if is_weather_request(cleaned):
        return True
    return any(marker in cleaned or marker in lowered for marker in _WEB_SEARCH_MARKERS)


def build_web_search_query(
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    location_city: str | None = None,
) -> str:
    cleaned = text.strip()
    city = resolve_weather_city(cleaned, history, location_city=location_city)
    if city and is_weather_request(cleaned, history):
        return build_weather_search_query(city)
    return cleaned


@dataclass(frozen=True)
class WebSearchPlan:
    """Resolved web_search pipeline input for chat_service."""

    search_query: str
    needs_location: bool = False


def resolve_web_search(
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    location_city: str | None = None,
) -> WebSearchPlan | None:
    """Return a web search plan, or None if this turn is not a realtime/web query."""
    cleaned = text.strip()
    if not cleaned or not is_web_search_query(cleaned):
        return None
    chat_history = history or []
    if is_weather_request(cleaned, chat_history):
        city = resolve_weather_city(cleaned, chat_history, location_city=location_city)
        if not city:
            return WebSearchPlan(search_query="", needs_location=True)
        return WebSearchPlan(search_query=build_weather_search_query(city))
    return WebSearchPlan(search_query=build_web_search_query(cleaned, chat_history))


def _recently_asked_weather_location(history: list[dict[str, str]]) -> bool:
    for item in reversed(history[-6:]):
        if item.get("role") != "assistant":
            continue
        content = str(item.get("content", ""))
        if "哪个城市" in content or WEATHER_ASK_LOCATION[:8] in content:
            return True
    return False
