"""Official web search APIs for Lumina ``web_search``.

Active when the corresponding env key is set (never commit secrets):

  TAVILY_API_KEY       — https://tavily.com
  BRAVE_API_KEY        — https://brave.com/search/api
  BOCHA_API_KEY        — https://open.bochaai.com
  SERPER_API_KEY       — https://serper.dev
  SERPAPI_API_KEY      — https://serpapi.com
  BING_SEARCH_API_KEY  — Azure Bing Web Search v7
  PERPLEXITY_API_KEY   — https://www.perplexity.ai (sonar)
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from secretary.agent.web_http import USER_AGENT
from secretary.agent.web_search import SEARCH_TIMEOUT, SearchResult

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
BOCHA_URL = "https://api.bochaai.com/v1/web-search"
SERPER_URL = "https://google.serper.dev/search"
SERPAPI_URL = "https://serpapi.com/search"
BING_API_URL = "https://api.bing.microsoft.com/v7.0/search"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

# engine name → env var (bing_api avoids clashing with HTML scraper "bing")
_ENV_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "brave": "BRAVE_API_KEY",
    "bocha": "BOCHA_API_KEY",
    "serper": "SERPER_API_KEY",
    "serpapi": "SERPAPI_API_KEY",
    "bing_api": "BING_SEARCH_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}

_SETTINGS_FIELD_MAP = {
    "TAVILY_API_KEY": "tavily_api_key",
    "BRAVE_API_KEY": "brave_api_key",
    "BOCHA_API_KEY": "bocha_api_key",
    "SERPER_API_KEY": "serper_api_key",
    "SERPAPI_API_KEY": "serpapi_api_key",
    "BING_SEARCH_API_KEY": "bing_search_api_key",
    "PERPLEXITY_API_KEY": "perplexity_api_key",
}


def _env_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    # pydantic Settings loads project .env into fields without mutating os.environ
    try:
        from secretary.config import settings

        attr = _SETTINGS_FIELD_MAP.get(name)
        if attr:
            return str(getattr(settings, attr, "") or "").strip()
    except Exception:
        return ""
    return ""


def configured_api_engines() -> tuple[str, ...]:
    """Return API engines that currently have a non-empty API key."""
    return tuple(engine for engine, env_name in _ENV_KEYS.items() if _env_key(env_name))


def api_key_for(engine: str) -> str:
    env_name = _ENV_KEYS.get(engine, "")
    return _env_key(env_name) if env_name else ""


def parse_tavily_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="tavily"))
        if len(results) >= limit:
            break
    return results


def parse_brave_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    web = payload.get("web") if isinstance(payload.get("web"), dict) else {}
    for item in (web or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("description") or item.get("snippet") or "").strip()
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="brave"))
        if len(results) >= limit:
            break
    return results


def parse_bocha_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    web_pages = data.get("webPages") if isinstance(data, dict) else None
    if not isinstance(web_pages, dict):
        web_pages = {}
    for item in web_pages.get("value") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(
            item.get("summary") or item.get("snippet") or item.get("description") or ""
        ).strip()
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="bocha"))
        if len(results) >= limit:
            break
    return results


def parse_serper_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in payload.get("organic") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("link") or item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="serper"))
        if len(results) >= limit:
            break
    return results


def parse_serpapi_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in payload.get("organic_results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("link") or item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="serpapi"))
        if len(results) >= limit:
            break
    return results


def parse_bing_api_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    web_pages = payload.get("webPages") if isinstance(payload.get("webPages"), dict) else {}
    for item in (web_pages or {}).get("value") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title or not url:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, engine="bing_api"))
        if len(results) >= limit:
            break
    return results


def parse_perplexity_response(payload: dict[str, Any], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in payload.get("search_results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or item.get("date") or "").strip()
        if not title or not url:
            continue
        results.append(
            SearchResult(title=title, url=url, snippet=snippet, engine="perplexity")
        )
        if len(results) >= limit:
            break
    if results:
        return results

    # Fallback: citation URLs only
    for cite in payload.get("citations") or []:
        url = str(cite).strip()
        if not url.startswith("http"):
            continue
        host = urlparse(url).netloc or url
        results.append(
            SearchResult(title=host, url=url, snippet="", engine="perplexity")
        )
        if len(results) >= limit:
            break
    return results


def search_tavily(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.post(
            TAVILY_URL,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": limit,
                "include_answer": False,
            },
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_tavily_response(payload, limit)


def search_brave(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(
            BRAVE_URL,
            params={"q": query, "count": str(limit)},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
                "User-Agent": USER_AGENT,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_brave_response(payload, limit)


def search_bocha(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.post(
            BOCHA_URL,
            json={
                "query": query,
                "freshness": "noLimit",
                "summary": True,
                "count": limit,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_bocha_response(payload, limit)


def search_serper(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.post(
            SERPER_URL,
            json={"q": query, "num": limit},
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_serper_response(payload, limit)


def search_serpapi(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(
            SERPAPI_URL,
            params={
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "num": str(limit),
            },
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_serpapi_response(payload, limit)


def search_bing_api(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(
            BING_API_URL,
            params={"q": query, "count": str(limit), "mkt": "zh-CN"},
            headers={
                "Ocp-Apim-Subscription-Key": api_key,
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_bing_api_response(payload, limit)


def search_perplexity(query: str, limit: int, *, api_key: str) -> list[SearchResult]:
    with httpx.Client(timeout=SEARCH_TIMEOUT, follow_redirects=True) as client:
        resp = client.post(
            PERPLEXITY_URL,
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 256,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    if not isinstance(payload, dict):
        return []
    return parse_perplexity_response(payload, limit)[:limit]


def _dispatch(engine: str, query: str, limit: int, api_key: str) -> list[SearchResult]:
    if engine == "tavily":
        return search_tavily(query, limit, api_key=api_key)
    if engine == "brave":
        return search_brave(query, limit, api_key=api_key)
    if engine == "bocha":
        return search_bocha(query, limit, api_key=api_key)
    if engine == "serper":
        return search_serper(query, limit, api_key=api_key)
    if engine == "serpapi":
        return search_serpapi(query, limit, api_key=api_key)
    if engine == "bing_api":
        return search_bing_api(query, limit, api_key=api_key)
    if engine == "perplexity":
        return search_perplexity(query, limit, api_key=api_key)
    return []


def make_api_search_fn(engine: str) -> Callable[[str, int], list[SearchResult]]:
    """Bind engine + env key into a SearchFn-compatible callable."""

    def _run(query: str, limit: int) -> list[SearchResult]:
        key = api_key_for(engine)
        if not key:
            logger.info("Skipping %s search: %s not set", engine, _ENV_KEYS.get(engine, "?"))
            return []
        return _dispatch(engine, query, limit, key)

    return _run


def api_preference_order(query: str, available: tuple[str, ...]) -> list[str]:
    """Language-aware priority among configured API engines."""
    if not available:
        return []
    chinese = bool(re.search(r"[\u4e00-\u9fff]", query))
    preferred = (
        [
            "bocha",
            "serper",
            "serpapi",
            "tavily",
            "brave",
            "bing_api",
            "perplexity",
        ]
        if chinese
        else [
            "tavily",
            "serper",
            "serpapi",
            "brave",
            "bing_api",
            "perplexity",
            "bocha",
        ]
    )
    return [name for name in preferred if name in available]
