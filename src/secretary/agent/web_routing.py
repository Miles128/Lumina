"""Route realtime / web queries to web_search instead of tool-less direct chat."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    "天气",
    "气温",
    "温度",
    "下雨",
    "下雪",
    "降雪",
    "降雨",
    "forecast",
    "weather",
    "news",
    "search for",
    "github",
    "gitlab",
    "最火",
    "热门",
    "火的项目",
    "trending",
    "开源项目",
    "上 GitHub",
    "上 github",
)

_LOCAL_CONTEXT_MARKERS = (
    "天气",
    "气温",
    "温度",
    "下雨",
    "下雪",
    "附近",
    "周边",
    "本地",
    "当地",
    "这里",
    "这边",
    "附近有什么",
)

_NON_CITY_PREFIXES = frozenset(
    {"今天", "明天", "后天", "本地", "当地", "现在", "这边", "这里", "最近"}
)

_CITY_WEATHER_RE = re.compile(r"([\u4e00-\u9fffA-Za-z·]{2,12}?)天气")
_CITY_ONLY = re.compile(r"^[\u4e00-\u9fffA-Za-z·]{2,12}市?$")

# Paths with spaces (e.g. ~/Documents/My Projects/) — broader than grounding._PATH_PATTERNS[0]
_LOCAL_PATH_RE = re.compile(
    r"(?:~/[^\s\u4e00-\u9fff\"'`<>|，。；;!?]+(?:\s[^\s\u4e00-\u9fff\"'`<>|，。；;!?]+)*|"
    r"/Users/[^/\s]+(?:/[^\s\u4e00-\u9fff\"'`<>|，。；;!?]+)*|"
    r"/(?:[A-Za-z0-9_.]+)(?:/(?:[A-Za-z0-9_.][A-Za-z0-9_. -]*))*)"
)

_LOCAL_FS_MARKERS = (
    "目录",
    "文件夹",
    "文件",
    "项目",
    "列出",
    "有哪些",
    "my project",
    "my projects",
    "简历",
    "readme",
    "本地",
    "list_dir",
    "file_read",
    "打开",
    "读取",
    "里有什么",
)


def _looks_like_local_filesystem_query(text: str) -> bool:
    """「查一下 ~/…」类本地盘问题不应走 web_search。"""
    if not _LOCAL_PATH_RE.search(text):
        return False
    lowered = text.lower()
    return any(marker in text or marker in lowered for marker in _LOCAL_FS_MARKERS)


def is_web_search_query(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if _looks_like_local_filesystem_query(cleaned):
        return False
    lowered = cleaned.lower()
    return any(marker in cleaned or marker in lowered for marker in _WEB_SEARCH_MARKERS)


def _query_needs_location_context(text: str) -> bool:
    cleaned = text.strip()
    return any(marker in cleaned for marker in _LOCAL_CONTEXT_MARKERS)


def _city_from_message(text: str, history: list[dict[str, str]] | None = None) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    match = _CITY_WEATHER_RE.search(cleaned)
    if match:
        city = match.group(1).strip().strip("的")
        if city and city not in _NON_CITY_PREFIXES:
            return city.rstrip("市")
    if history and _recent_local_context_without_city(history):
        if _CITY_ONLY.fullmatch(cleaned):
            return cleaned.rstrip("市")
    return None


def resolve_client_location(
    location_city: str | None = None,
    *,
    location_lat: float | None = None,
    location_lng: float | None = None,
) -> str | None:
    """City from client hint only; reverse-geocoding removed with location UI."""
    if location_city:
        city = location_city.strip().rstrip("市")
        if city:
            return city
    return None


def _strip_rhetorical_web_prefix(text: str) -> str:
    """Remove filler before the real web query (e.g. 「你会上网查吗？GitHub…」)."""
    cleaned = text.strip()
    prefixes = (
        "你会上网查这个信息吗？",
        "你会上网查吗？",
        "你能上网查一下吗？",
        "你能上网查吗？",
        "帮我联网查一下",
        "帮我联网查",
        "上网查一下",
        "联网查一下",
    )
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip().lstrip("，,？? ")
            break
    return cleaned or text.strip()


def build_search_query(
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    location_city: str | None = None,
    location_lat: float | None = None,
    location_lng: float | None = None,
) -> str:
    """Build Bing query; inject device city only when the question needs local context."""
    cleaned = _strip_rhetorical_web_prefix(text)
    city = _city_from_message(cleaned, history) or resolve_client_location(
        location_city,
        location_lat=location_lat,
        location_lng=location_lng,
    )
    needs_local = _query_needs_location_context(cleaned) or (
        history is not None and city is not None and _recent_local_context_without_city(history)
    )
    if city and needs_local:
        weather_turn = any(
            m in cleaned for m in ("天气", "气温", "温度", "下雨", "下雪", "weather", "forecast")
        ) or (
            history is not None
            and _CITY_ONLY.fullmatch(cleaned)
            and _recent_weather_without_city(history)
        )
        if weather_turn:
            return f"{city} 今天天气 气温"
        return f"{cleaned} {city}"
    return cleaned


@dataclass(frozen=True)
class WebSearchPlan:
    """Resolved web_search pipeline input for chat_service."""

    search_query: str


def resolve_web_search(
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    location_city: str | None = None,
    location_lat: float | None = None,
    location_lng: float | None = None,
) -> WebSearchPlan | None:
    """Return a web search plan, or None if this turn is not a realtime/web query."""
    cleaned = text.strip()
    if not cleaned or not is_web_search_query(cleaned):
        return None
    query = build_search_query(
        cleaned,
        history,
        location_city=location_city,
        location_lat=location_lat,
        location_lng=location_lng,
    )
    return WebSearchPlan(search_query=query)


def _recent_weather_without_city(history: list[dict[str, str]]) -> bool:
    for item in reversed(history[-6:]):
        if item.get("role") != "user":
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if any(
            m in content for m in ("天气", "气温", "温度", "下雨", "下雪", "weather", "forecast")
        ) and _city_from_message(content) is None:
            return True
        return False
    return False


def _recent_local_context_without_city(history: list[dict[str, str]]) -> bool:
    """Prior user turn needed local context (e.g. weather) but named no city."""
    for item in reversed(history[-6:]):
        if item.get("role") != "user":
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if _query_needs_location_context(content) and _city_from_message(content) is None:
            return True
        return False
    return False
