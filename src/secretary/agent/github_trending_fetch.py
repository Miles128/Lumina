"""Fetch GitHub trending via HTML (when available) or Search API fallback."""

from __future__ import annotations

import re
import urllib.parse
from datetime import UTC, datetime, timedelta

import httpx

from secretary.agent.web_http import USER_AGENT

_SKIP_OWNERS = frozenset(
    {
        "login",
        "signup",
        "trending",
        "features",
        "settings",
        "explore",
        "topics",
        "collections",
        "sponsors",
        "apps",
        "orgs",
        "organizations",
    }
)


def is_github_trending_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return False
    path = parsed.path.rstrip("/")
    return path == "/trending" or path.startswith("/trending/")


def _since_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    since = (query.get("since") or ["weekly"])[0].lower()
    if since in {"daily", "weekly", "monthly"}:
        return since
    return "weekly"


def _since_label(since: str) -> str:
    return {"daily": "今日", "weekly": "本周", "monthly": "本月"}.get(since, "本周")


def _parse_repos_from_html(html: str, *, limit: int = 12) -> list[tuple[str, str]]:
    repos: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for owner, name in re.findall(
        r'href="/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"',
        html,
    ):
        key = (owner.lower(), name.lower())
        if owner.lower() in _SKIP_OWNERS or key in seen:
            continue
        seen.add(key)
        repos.append((owner, name))
        if len(repos) >= limit:
            break
    return repos


def _fetch_html_trending(url: str, *, timeout: float = 25.0) -> list[tuple[str, str]]:
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError:
        return []
    if len(html) < 5000:
        return []
    return _parse_repos_from_html(html)


def _fetch_search_api_trending(since: str, *, limit: int = 12) -> list[dict[str, object]]:
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(since, 7)
    since_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    query = f"stars:>50 pushed:>{since_date}"
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": str(limit),
        }
    )
    api_url = f"https://api.github.com/search/repositories?{params}"
    try:
        with httpx.Client(
            timeout=20.0,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
        ) as client:
            resp = client.get(api_url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    rows: list[dict[str, object]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "")
        if "/" not in full_name:
            continue
        rows.append(
            {
                "full_name": full_name,
                "stars": item.get("stargazers_count", 0),
                "description": str(item.get("description") or "")[:140],
            }
        )
    return rows


def _format_repo_list(
    repos: list[tuple[str, str]],
    *,
    since: str,
    source: str,
) -> str:
    label = _since_label(since)
    lines = [
        f"## GitHub 热门仓库（{label}）",
        f"来源：{source}",
        "",
    ]
    for index, (owner, name) in enumerate(repos, start=1):
        lines.append(f"{index}. **{owner}/{name}** — https://github.com/{owner}/{name}")
    return "\n".join(lines)


def _format_api_list(
    rows: list[dict[str, object]],
    *,
    since: str,
    source: str,
) -> str:
    label = _since_label(since)
    lines = [
        f"## GitHub 近期高星仓库（{label}，Search API 近似榜单）",
        f"来源：{source}",
        "说明：github.com/trending 页面未返回可解析列表时使用 GitHub Search API（按近段 push + star 排序）。",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        full_name = str(row.get("full_name", ""))
        stars = row.get("stars", 0)
        desc = str(row.get("description") or "")
        lines.append(f"{index}. **{full_name}** — ⭐ {stars}")
        if desc:
            lines.append(f"   {desc}")
    return "\n".join(lines)


def fetch_github_trending(url: str, *, max_chars: int = 6000) -> str:
    """Return formatted trending list; never an empty HTML skeleton."""
    since = _since_from_url(url)
    repos = _fetch_html_trending(url)
    if repos:
        text = _format_repo_list(
            repos,
            since=since,
            source=url,
        )
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    api_rows = _fetch_search_api_trending(since)
    if api_rows:
        text = _format_api_list(
            api_rows,
            since=since,
            source="https://api.github.com/search/repositories",
        )
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    return (
        "Error: 无法获取 GitHub Trending（页面超时/无列表，Search API 也无结果）。"
        "请稍后重试或缩小范围（如指定语言 Python）。"
    )
