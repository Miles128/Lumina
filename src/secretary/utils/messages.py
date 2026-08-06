"""Human-readable connector status messages + shared text helpers."""

from __future__ import annotations

import json
import re


def format_connector_message(message: str, max_len: int = 240) -> str:
    text = message.strip()
    if not text:
        return "未检测"

    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                hint = error.get("hint") or error.get("message")
                if hint:
                    return _truncate(str(hint), max_len)
            direct = payload.get("message")
            if direct:
                return _truncate(str(direct), max_len)

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("Waiting for Chrome")
    ]
    if lines:
        return _truncate(lines[0], max_len)
    return _truncate(text, max_len)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def re_search_json_fence(cleaned: str) -> str | None:
    """Extract text inside the first ```json ... ``` (or ``` ... ```) fence."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if match:
        return match.group(1).strip()
    return None
