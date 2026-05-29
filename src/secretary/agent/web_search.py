"""Multi-engine web search tool for Agent Loop.

Supports: Bing (default, most reliable), DuckDuckGo, Google, Baidu, Sogou.
Falls back through engines when one is blocked or returns no results.
"""

from __future__ import annotations

import base64
import logging
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from secretary.agent.loop import Tool

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT = 15
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


def _fetch_html(
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    request_headers = {**_DEFAULT_HEADERS, **(headers or {})}
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        if method == "POST":
            resp = client.post(url, data=data, headers=request_headers)
        else:
            resp = client.get(url, params=params, headers=request_headers)
        resp.raise_for_status()
        return resp.text


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
    results: list[SearchResult] = []
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
        snippet_match = re.search(r'<p[^>]*>([\s\S]*?)</p>', block)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="bing"))
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


SearchFn = Callable[[str, int], list[SearchResult]]

_ENGINES: dict[str, SearchFn] = {
    "bing": _bing,
    "duckduckgo": _ddg,
    "google": _google,
    "baidu": _baidu,
    "sogou": _sogou,
}

_ENGINE_FALLBACK = ["bing", "duckduckgo", "google", "sogou", "baidu"]


def run_search(query: str, engine: str, limit: int) -> tuple[list[SearchResult], str]:
    """Run a search, falling back when an engine errors or returns no results."""
    normalized = engine.lower().strip()
    fn = _ENGINES.get(normalized)
    if fn is None:
        available = ", ".join(_ENGINES.keys())
        raise ValueError(f"unknown engine '{engine}'. Available: {available}")

    engines_to_try = [normalized]
    engines_to_try.extend(name for name in _ENGINE_FALLBACK if name != normalized)

    errors: list[str] = []
    for name in engines_to_try:
        search_fn = _ENGINES[name]
        try:
            results = search_fn(query, limit)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("Search engine %s failed: %s", name, exc)
            continue
        if results:
            return results, name
        errors.append(f"{name}: no results")

    detail = "; ".join(errors) if errors else "no engines tried"
    raise RuntimeError(f"all search engines failed for query '{query}' ({detail})")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web using multiple search engines. "
        "Supports: bing (default), duckduckgo, google, baidu, sogou. "
        "Can use multiple engines and merge results."
    )
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "engine": {
                    "type": "string",
                    "description": "Search engine: bing, duckduckgo, google, baidu, sogou, or 'all' (default: bing)",
                    "enum": ["bing", "duckduckgo", "google", "baidu", "sogou", "all"],
                },
                "limit": {"type": "integer", "description": "Max results per engine (default 5)"},
            },
            "required": ["query"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        query = arguments.get("query", "").strip()
        if not query:
            return "Error: empty search query"

        engine = arguments.get("engine", "bing").lower().strip()
        limit = min(arguments.get("limit", 5), MAX_RESULTS_PER_ENGINE)

        if engine == "all":
            return self._search_all(query, limit)

        try:
            results, used_engine = run_search(query, engine, limit)
        except (RuntimeError, ValueError) as exc:
            return f"Error: {exc}"

        return _format_results(results, query, engine_note=used_engine)

    def _search_all(self, query: str, limit: int) -> str:
        all_results: list[SearchResult] = []
        errors: list[str] = []

        for name in _ENGINE_FALLBACK:
            fn = _ENGINES[name]
            try:
                results = fn(query, limit)
                all_results.extend(results)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                logger.warning("Search engine %s failed: %s", name, exc)

        if not all_results:
            return "Error: all search engines failed.\n" + "\n".join(errors)

        seen_urls: set[str] = set()
        deduped: list[SearchResult] = []
        for result in all_results:
            normalized = (
                result.url.rstrip("/").replace("https://", "").replace("http://", "www.").split("?")[0]
            )
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                deduped.append(result)

        deduped.sort(key=lambda result: (result.engine == "bing", result.engine == "google"), reverse=True)

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
