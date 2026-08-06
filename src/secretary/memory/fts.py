"""Shared FTS5 query sanitization for memory SQLite stores."""

from __future__ import annotations

import re

_FTS_SPECIAL = re.compile(r'[`*"()|:]')


def sanitize_fts_query(query: str) -> str:
    """Strip FTS special chars; join remaining tokens with OR (empty-safe)."""
    cleaned = _FTS_SPECIAL.sub("", query).strip()
    if not cleaned:
        return query
    tokens = cleaned.split()
    return " OR ".join(tokens)
