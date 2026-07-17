"""Small text helpers shared across agent tools / loop."""

from __future__ import annotations

import re

_DEFAULT_SUFFIX = "\n...[truncated]"


def truncate_chars(text: str, limit: int, *, suffix: str = _DEFAULT_SUFFIX) -> str:
    """Truncate ``text`` to ``limit`` characters, appending ``suffix`` when cut."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + suffix


def strip_html(text: str, *, replacement: str = "") -> str:
    """Remove HTML tags from ``text``, replacing them with ``replacement``."""
    return re.sub(r"<[^>]+>", replacement, text)
