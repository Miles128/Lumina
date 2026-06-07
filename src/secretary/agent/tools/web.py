"""Web fetch tool."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from secretary.agent.tools.base import Tool


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch and extract text content from a URL."
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)"},
            },
            "required": ["url"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        url = str(arguments.get("url", "")).strip()
        max_chars = int(arguments.get("max_chars", 3000) or 3000)
        if not url.startswith(("http://", "https://")):
            return "Error: only http/https URLs are supported"
        try:
            from secretary.agent.github_trending_fetch import (
                fetch_github_trending,
                is_github_trending_url,
            )

            if is_github_trending_url(url):
                return fetch_github_trending(url, max_chars=max_chars)

            body = _fetch_url(url)
            body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL)
            body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL)
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
            if len(body) > max_chars:
                body = body[:max_chars] + "..."
            return body or "(empty response)"
        except Exception as exc:
            return f"Error fetching URL: {exc}"


def _fetch_url(url: str) -> str:
    with httpx.Client(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        response = client.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        return response.text
