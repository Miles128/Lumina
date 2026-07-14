"""Multi-engine web search tool for Agent Loop.

Supports: Bing (default, most reliable), DuckDuckGo, Google, Baidu, Sogou.
Falls back through engines when one is blocked or returns no results.
"""

from __future__ import annotations

import base64
import logging
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from secretary.agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT = 15
FETCH_RETRIES = 2
RETRY_BACKOFF_SEC = 0.6
MAX_RESULTS_PER_ENGINE = 8
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "engine": self.engine}


SearchFn = Callable[[str, int], list[SearchResult]]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _decode_bing_url(href: str) -> str:
    href = href.replace("&amp;", "&")
    match = re.search(r"[?&]u=([^&]+)", href)
    if not match:
        return href
    encoded = match.group(1)
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    padding = "=" * (-len(encoded) % 4)
    try:
        return base64.b64decode(encoded + padding).decode("utf-8", errors="ignore")
    except (ValueError, UnicodeDecodeError):
        return href


def _query_prefers_chinese_engines(query: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", query))


_API_ENGINE_NAMES = frozenset(
    {"tavily", "brave", "bocha", "serper", "serpapi", "bing_api", "perplexity"}
)
# Populated lazily; tests may replace/patch this dict.
_API_ENGINES: dict[str, SearchFn] = {}


def configured_api_engines() -> tuple[str, ...]:
    from secretary.agent.web_search_providers import configured_api_engines as _cfg

    return _cfg()


def _ensure_api_engines() -> dict[str, SearchFn]:
    if not _API_ENGINES:
        from secretary.agent.web_search_providers import make_api_search_fn

        _API_ENGINES.update(
            {
                name: make_api_search_fn(name)
                for name in (
                    "tavily",
                    "brave",
                    "bocha",
                    "serper",
                    "serpapi",
                    "bing_api",
                    "perplexity",
                )
            }
        )
    return _API_ENGINES


def fallback_engine_order(primary: str | None, query: str) -> list[str]:
    """Engine try-order: configured APIs first, then HTML scrapers by language."""
    from secretary.agent.web_search_providers import api_preference_order

    if _query_prefers_chinese_engines(query):
        html = ["bing", "baidu", "sogou", "duckduckgo", "google"]
    else:
        html = ["bing", "duckduckgo", "google", "sogou", "baidu"]
    api = api_preference_order(query, configured_api_engines())
    base = api + [name for name in html if name not in api]
    known = set(_ENGINES) | set(_API_ENGINE_NAMES)
    if primary and primary in known:
        return [primary] + [name for name in base if name != primary]
    return list(base)


def _fetch_html(
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    request_headers = {**_DEFAULT_HEADERS, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(FETCH_RETRIES + 1):
        try:
            with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
                if method == "POST":
                    resp = client.post(url, data=data, headers=request_headers)
                else:
                    resp = client.get(url, params=params, headers=request_headers)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPError as error:
            last_error = error
            if attempt < FETCH_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("fetch failed without error")


def _ddg(query: str, limit: int) -> list[SearchResult]:
    html = _fetch_html(
        "POST",
        "https://html.duckduckgo.com/html/",
        data={"q": query, "b": ""},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if "anomaly-modal" in html or "bots use DuckDuckGo" in html:
        logger.info("DuckDuckGo blocked request with bot challenge")
        return []

    results: list[SearchResult] = []
    for match in re.finditer(
        r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    ):
        href = match.group(1).replace("&amp;", "&")
        title = _strip_html(match.group(2))
        if href.startswith("//duckduckgo.com/l/?uddg="):
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if not title or not href:
            continue
        results.append(SearchResult(title=title, url=href, snippet="", engine="duckduckgo"))
        if len(results) >= limit:
            break

    if not results:
        for match in re.finditer(
            r'<a rel="nofollow" href="(https?://[^"]+)"[^>]*>([^<]{2,200})</a>',
            html,
        ):
            href = match.group(1).replace("&amp;", "&")
            title = _strip_html(match.group(2))
            if "duckduckgo.com" in href or not title:
                continue
            results.append(SearchResult(title=title, url=href, snippet="", engine="duckduckgo"))
            if len(results) >= limit:
                break

    snippet_blocks = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
    for index, block in enumerate(snippet_blocks):
        if index < len(results):
            results[index].snippet = _strip_html(block)
    return results


def _google(query: str, limit: int) -> list[SearchResult]:
    html = _fetch_html(
        "GET",
        "https://www.google.com/search",
        params={"q": query, "num": str(limit), "hl": "zh-CN"},
    )
    if "unusual traffic" in html.lower() or "/sorry/" in html:
        logger.info("Google blocked request")
        return []

    results: list[SearchResult] = []
    for match in re.finditer(r'<a href="/url\?q=([^&]+)&[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL):
        href = urllib.parse.unquote(match.group(1))
        title = _strip_html(match.group(2))
        if (
            not title
            or not href
            or href.startswith("https://accounts.google.com")
            or href.startswith("/search")
        ):
            continue
        results.append(SearchResult(title=title, url=href, snippet="", engine="google"))
        if len(results) >= limit:
            break

    for match in re.finditer(r'<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL):
        index = len([result for result in results if not result.snippet])
        if index < len(results):
            results[index].snippet = _strip_html(match.group(1))
    return results


def _bing(query: str, limit: int) -> list[SearchResult]:
    html = _fetch_html(
        "GET",
        "https://www.bing.com/search",
        params={"q": query, "count": str(limit), "setlang": "zh-CN", "cc": "CN"},
    )
    lowered = html.lower()
    has_results = "b_algo" in html or "bing.com/ck/a" in html
    if not has_results and (
        "captcha" in lowered
        or "unusual traffic" in lowered
        or "b_search" in lowered
    ):
        logger.info("Bing blocked or returned no result markup")
        return []

    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for block in re.split(r'<li class="b_algo"[^>]*>', html)[1:]:
        heading = re.search(
            r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>\s*</h2>',
            block,
        )
        if not heading:
            continue
        title = _strip_html(heading.group(2))
        url = _decode_bing_url(heading.group(1))
        if not title or not url or "bing.com/aclick" in url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        snippet_match = re.search(r'<p[^>]*>([\s\S]*?)</p>', block)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="bing"))
        if len(results) >= limit:
            return results

    for match in re.finditer(r'href="(https://www\.bing\.com/ck/a[^"]+)"', html):
        raw_href = match.group(1).replace("&amp;", "&")
        url = _decode_bing_url(raw_href)
        if (
            not url
            or not url.startswith("http")
            or "bing.com" in url
            or "microsoft.com" in url
            or url in seen_urls
        ):
            continue
        seen_urls.add(url)
        block_start = max(0, match.start() - 400)
        block_end = min(len(html), match.end() + 600)
        block = html[block_start:block_end]
        title = ""
        aria = re.search(r'aria-label="([^"]{3,120})"', block)
        if aria:
            title = _strip_html(aria.group(1))
        if not title:
            clamp = re.search(
                r'class="[^"]*b_lineclamp[^"]*"[^>]*>([^<]{4,200})<',
                block,
            )
            if clamp:
                title = _strip_html(clamp.group(1))
        if not title:
            title = url
        results.append(
            SearchResult(title=title, url=url, snippet="", engine="bing"),
        )
        if len(results) >= limit:
            break
    return results


def _baidu(query: str, limit: int) -> list[SearchResult]:
    html = _fetch_html(
        "GET",
        "https://www.baidu.com/s",
        params={"wd": query, "rn": str(limit), "ie": "utf-8"},
    )
    if "wappass.baidu.com" in html or "网络不给力" in html:
        logger.info("Baidu blocked request with captcha")
        return []

    results: list[SearchResult] = []
    for match in re.finditer(
        r'<h3[^>]*class="[^"]*t[^"]*"[^>]*>.*?<a href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    ):
        href = match.group(1)
        title = _strip_html(match.group(2))
        if not title or not href:
            continue
        if href.startswith("/"):
            href = "https://www.baidu.com" + href
        results.append(SearchResult(title=title, url=href, snippet="", engine="baidu"))
        if len(results) >= limit:
            break

    for match in re.finditer(r'<span class="content-right_[^"]*">(.*?)</span>', html, re.DOTALL):
        index = len([result for result in results if not result.snippet])
        if index < len(results):
            results[index].snippet = _strip_html(match.group(1))
    if not any(result.snippet for result in results):
        for match in re.finditer(r'<div class="c-abstract[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL):
            index = len([result for result in results if not result.snippet])
            if index < len(results):
                results[index].snippet = _strip_html(match.group(1))
    return results


def _sogou(query: str, limit: int) -> list[SearchResult]:
    html = _fetch_html(
        "GET",
        "https://www.sogou.com/web",
        params={"query": query, "num": str(limit)},
        headers={"Referer": "https://www.sogou.com/"},
    )
    if "antispider" in html or len(html) < 2000:
        logger.info("Sogou blocked request with antispider page")
        return []

    results: list[SearchResult] = []
    for match in re.finditer(
        r'<h3[^>]*class="[^"]*vr-title[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
        html,
    ):
        href = match.group(1)
        title = _strip_html(match.group(2))
        if not title or not href:
            continue
        results.append(SearchResult(title=title, url=href, snippet="", engine="sogou"))
        if len(results) >= limit:
            break

    if not results:
        for match in re.finditer(r'<h3[^>]*>.*?<a href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL):
            href = match.group(1)
            title = _strip_html(match.group(2))
            if not title or not href or "antispider" in href:
                continue
            results.append(SearchResult(title=title, url=href, snippet="", engine="sogou"))
            if len(results) >= limit:
                break

    for match in re.finditer(r'<p class="str-text-info[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL):
        index = len([result for result in results if not result.snippet])
        if index < len(results):
            results[index].snippet = _strip_html(match.group(1))
    return results


def _ddg_instant(query: str, limit: int) -> list[SearchResult]:
    """JSON API fallback when HTML engines are blocked or empty."""
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_redirect": "1",
                "no_html": "1",
                "skip_disambig": "1",
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()

    results: list[SearchResult] = []
    abstract = str(payload.get("AbstractText", "")).strip()
    abstract_url = str(payload.get("AbstractURL", "")).strip()
    heading = str(payload.get("Heading", "")).strip() or query
    if abstract and abstract_url:
        results.append(
            SearchResult(
                title=heading,
                url=abstract_url,
                snippet=abstract,
                engine="duckduckgo_instant",
            )
        )

    def _append_topic(item: dict[str, Any]) -> None:
        if len(results) >= limit:
            return
        text = str(item.get("Text", "")).strip()
        url = str(item.get("FirstURL", "")).strip()
        if not text or not url:
            return
        title = text.split(" - ", 1)[0].strip() or text[:80]
        snippet = text if len(text) <= 200 else text[:200] + "…"
        results.append(
            SearchResult(title=title, url=url, snippet=snippet, engine="duckduckgo_instant")
        )

    for topic in payload.get("RelatedTopics", []):
        if not isinstance(topic, dict):
            continue
        if "Topics" in topic:
            for nested in topic.get("Topics", []):
                if isinstance(nested, dict):
                    _append_topic(nested)
        else:
            _append_topic(topic)
    return results[:limit]


_ENGINES: dict[str, SearchFn] = {
    "bing": _bing,
    "duckduckgo": _ddg,
    "google": _google,
    "baidu": _baidu,
    "sogou": _sogou,
}

_ENGINE_FALLBACK = ["bing", "duckduckgo", "google", "sogou", "baidu"]


def _try_ddg_instant(query: str, limit: int, errors: list[str]) -> tuple[list[SearchResult], str] | None:
    try:
        results = _ddg_instant(query, limit)
    except Exception as exc:
        errors.append(f"duckduckgo_instant: {exc}")
        logger.warning("DuckDuckGo instant API failed: %s", exc)
        return None
    if results:
        return results, "duckduckgo_instant"
    errors.append("duckduckgo_instant: no results")
    return None


def run_search(query: str, engine: str, limit: int) -> tuple[list[SearchResult], str]:
    """Run a search, falling back when an engine errors or returns no results."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("empty search query")

    api_engines = _ensure_api_engines()
    all_engines: dict[str, SearchFn] = {**_ENGINES, **api_engines}
    configured_apis = set(configured_api_engines())

    normalized = engine.lower().strip()
    available_names = [
        *_ENGINES.keys(),
        *[name for name in _API_ENGINE_NAMES if name in configured_apis],
        "auto",
    ]
    if normalized == "auto":
        engines_to_try = fallback_engine_order(None, cleaned_query)
    elif normalized in _API_ENGINE_NAMES and normalized not in configured_apis:
        available = ", ".join(available_names)
        raise ValueError(f"unknown engine '{engine}'. Available: {available}")
    elif normalized not in all_engines:
        available = ", ".join(available_names)
        raise ValueError(f"unknown engine '{engine}'. Available: {available}")
    else:
        engines_to_try = fallback_engine_order(normalized, cleaned_query)

    errors: list[str] = []
    for name in engines_to_try:
        search_fn = all_engines.get(name)
        if search_fn is None:
            continue
        try:
            results = search_fn(cleaned_query, limit)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("Search engine %s failed: %s", name, exc)
            continue
        if results:
            return results, name
        errors.append(f"{name}: no results")

    instant = _try_ddg_instant(cleaned_query, limit, errors)
    if instant is not None:
        return instant

    detail = "; ".join(errors) if errors else "no engines tried"
    raise RuntimeError(f"all search engines failed for query '{cleaned_query}' ({detail})")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web. Prefer auto (API providers when configured: tavily/brave/bocha, "
        "then HTML engines bing/duckduckgo/google/baidu/sogou)."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "engine": {
                    "type": "string",
                    "description": (
                        "Search engine: auto (default), tavily, brave, bocha, serper, "
                        "serpapi, bing_api, perplexity, bing, duckduckgo, google, baidu, "
                        "sogou, or all"
                    ),
                    "enum": [
                        "auto",
                        "tavily",
                        "brave",
                        "bocha",
                        "serper",
                        "serpapi",
                        "bing_api",
                        "perplexity",
                        "bing",
                        "duckduckgo",
                        "google",
                        "baidu",
                        "sogou",
                        "all",
                    ],
                },
                "limit": {"type": "integer", "description": "Max results per engine (default 5)"},
            },
            "required": ["query"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        query = arguments.get("query", "").strip()
        if not query:
            return ToolResult.failure(
                "Error: empty search query",
                error_type="validation",
                retryable=False,
            )

        engine = str(arguments.get("engine", "auto")).lower().strip() or "auto"
        limit = min(arguments.get("limit", 5), MAX_RESULTS_PER_ENGINE)

        if engine == "all":
            return self._search_all(query, limit)

        try:
            results, used_engine = run_search(query, engine, limit)
        except (RuntimeError, ValueError) as exc:
            return ToolResult.failure(
                f"Error: {exc}",
                error_type="internal",
                retryable=False,
            )

        return _format_results(results, query, engine_note=used_engine)

    def _search_all(self, query: str, limit: int) -> str | ToolResult:
        all_results: list[SearchResult] = []
        errors: list[str] = []
        api_engines = _ensure_api_engines()
        combined = {**_ENGINES, **api_engines}

        for name in fallback_engine_order(None, query):
            fn = combined.get(name)
            if fn is None:
                continue
            try:
                results = fn(query, limit)
                all_results.extend(results)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Search engine %s failed: %s", name, exc)

        if not all_results:
            instant = _try_ddg_instant(query, limit, errors)
            if instant is not None:
                all_results.extend(instant[0])

        if not all_results:
            return ToolResult.failure(
                "Error: all search engines failed.\n" + "\n".join(errors),
                error_type="internal",
                retryable=False,
            )

        seen_urls: set[str] = set()
        deduped: list[SearchResult] = []
        for result in all_results:
            normalized = (
                result.url.rstrip("/").replace("https://", "").replace("http://", "www.").split("?")[0]
            )
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                deduped.append(result)

        deduped.sort(
            key=lambda result: (
                result.engine in _API_ENGINE_NAMES,
                result.engine == "bing",
                result.engine == "google",
            ),
            reverse=True,
        )

        header = f"🔍 '{query}' — {len(deduped)} results from {len({r.engine for r in deduped})} engines"
        if errors:
            header += f" ({len(errors)} engines failed)"
        return header + "\n" + _format_results(deduped[: limit * 3], query, show_engine=True)


def _format_results(
    results: list[SearchResult],
    query: str,
    *,
    show_engine: bool = False,
    engine_note: str | None = None,
) -> str:
    header = f"🔍 '{query}' — {len(results)} results"
    if engine_note:
        header += f" (via {engine_note})"
    lines = [header]
    for index, result in enumerate(results, 1):
        engine_tag = f" [{result.engine}]" if show_engine else ""
        lines.append(f"{index}. {result.title}{engine_tag}")
        lines.append(f"   {result.url}")
        if result.snippet:
            snippet = result.snippet[:200]
            if len(result.snippet) > 200:
                snippet += "…"
            lines.append(f"   {snippet}")
    return "\n".join(lines)
