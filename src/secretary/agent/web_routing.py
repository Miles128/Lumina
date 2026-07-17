"""Route realtime / web queries to web_search instead of tool-less direct chat."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from secretary.config import Settings
    from secretary.services.agent_config import AgentConfigStore

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# LLM-based web search intent router (fallback when keyword rules miss)
# ---------------------------------------------------------------------------

_WEB_INTENT_SYSTEM = """你是联网搜索意图判断器。判断本轮用户消息是否需要联网搜索才能给出有用回答，只输出一个 JSON 对象，不要其他文字。

字段：
- needs_web: true | false —— 是否需要联网
- query: 字符串 —— 当 needs_web=true 时给出精炼的搜索关键词（去掉"是什么/介绍一下"等寒暄，保留实体和时间/语言等限定）；needs_web=false 时留空字符串
- reason: 一句话说明判断理由（仅日志用，不复述用户原话）

判定为 needs_web=true 的典型情形：
- 询问具体产品/公司/人物/项目/技术（如 "alva.ai 是什么" "xx 公司怎么样" "xxx 是谁"）
- 实时信息（天气、新闻、股价、汇率、榜单、trending、最新动态）
- 知识性问题且 LLM 自身知识可能过时或不准确（新模型、新版本、新政策、新事件）
- 用户明确要求搜索（搜一下、查一下、联网、上网、百度、谷歌等）

判定为 needs_web=false 的情形：
- 闲聊、打招呼、致谢、确认（你好/谢谢/好的/嗯嗯）
- 写作、翻译、改写、解释概念等纯 LLM 能力可完成的任务
- 询问本机文件、目录、项目结构、记忆、画像（这些走本地工具，不是联网）
- 代码问题、算法问题、数学问题等不需实时数据的
- 对上文的纯逻辑追问、纠错、抱怨（如"你确定吗""再说一遍""不对"）

判定为 needs_web=true 的跟进情形（结合历史判断）：
- 用户要求提供引用、来源、链接、出处（如"有引用吗""带来源""给链接""哪里看到的"）
- 用户追问上文提及的产品/公司/人物/项目的细节，而该信息需要联网核实
- 用户质疑上文回答的准确性，需要联网验证（如"真的吗""你确定 alva.ai 是做这个的"）

重要：当用户要求引用/来源/链接时，一律 needs_web=true，因为 LLM 无法自己生成真实可访问的引用。"""


def _parse_web_intent(raw: str, fallback_query: str) -> tuple[bool, str, str]:
    """Parse LLM web-intent response. On any error, return (False, "", "")."""
    cleaned = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("web intent LLM returned non-JSON: %r", raw[:200])
        return False, "", ""
    if not isinstance(payload, dict):
        return False, "", ""
    needs_web = bool(payload.get("needs_web", False))
    query = str(payload.get("query", "") or "").strip()
    reason = str(payload.get("reason", "") or "").strip()
    if needs_web and not query:
        query = fallback_query
    return needs_web, (query if needs_web else ""), reason


class WebIntentRouter:
    """LLM-based web search intent classifier.

    Used as a fallback when keyword-based ``resolve_web_search`` returns None.
    Disabled by default; enable via ``settings.web_intent_router_enabled``.
    """

    def __init__(
        self,
        settings: Settings,
        agent_config_store: AgentConfigStore | None = None,
    ) -> None:
        self._settings = settings
        self._agent_config_store = agent_config_store

    def judge(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> WebSearchPlan | None:
        """Return a WebSearchPlan if the LLM judges this needs web search, else None.

        Any error (LLM unavailable, timeout, parse failure) returns None so the
        main chat flow continues uninterrupted.
        """
        from secretary.agent.llm_client import chat_completion
        from secretary.agent.llm_config import resolve_llm_config

        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        if llm_config is None:
            logger.info("web intent LLM skipped: no llm_config")
            return None

        user_content = message
        if history:
            recent = history[-6:]
            lines = [f"{item['role']}: {item['content']}" for item in recent]
            user_content = (
                "近期对话（供路由参考，用户本轮消息在最后）：\n"
                + "\n".join(lines)
                + f"\n\n本轮用户消息：\n{message}"
            )

        logger.info("web intent LLM judging: %r", message[:120])
        try:
            raw = chat_completion(
                llm_config,
                [
                    {"role": "system", "content": _WEB_INTENT_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                timeout=15.0,
            )
        except Exception as exc:
            logger.warning("web intent LLM judge failed: %s", exc)
            return None

        needs_web, query, reason = _parse_web_intent(raw, fallback_query=message.strip())
        logger.info(
            "web intent LLM result: needs_web=%s query=%r reason=%s",
            needs_web,
            query[:80],
            reason[:120],
        )
        if not needs_web:
            return None
        return WebSearchPlan(search_query=query or message.strip())


def resolve_web_search_with_llm_fallback(
    text: str,
    history: list[dict[str, str]] | None = None,
    *,
    location_city: str | None = None,
    location_lat: float | None = None,
    location_lng: float | None = None,
    llm_router: WebIntentRouter | None = None,
) -> WebSearchPlan | None:
    """Keyword route first; if miss and llm_router provided, let LLM judge.

    This keeps the fast path (keyword match → instant) and only spends an LLM
    call when keyword rules miss — covering cases like "alva.ai 是什么东西" that
    contain no trigger words but clearly need web data.
    """
    plan = resolve_web_search(
        text,
        history,
        location_city=location_city,
        location_lat=location_lat,
        location_lng=location_lng,
    )
    if plan is not None:
        logger.info("web route: keyword hit query=%r", plan.search_query[:80])
        return plan
    if llm_router is None:
        logger.info("web route: keyword miss, no LLM router enabled")
        return None
    logger.info("web route: keyword miss, delegating to LLM judge")
    return llm_router.judge(text, history)
