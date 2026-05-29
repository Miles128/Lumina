"""Deterministic ingest helpers."""

from __future__ import annotations

import hashlib
import re

from secretary.core.types import MemoryChunk, SourceKind


def stable_chunk_id(source: SourceKind, key: str) -> str:
    digest = hashlib.sha256(f"{source.value}:{key}".encode()).hexdigest()
    return digest[:32]


def normalize_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def chunk_text(
    *,
    source: SourceKind,
    key: str,
    title: str,
    body: str,
    metadata: dict[str, str] | None = None,
    max_chars: int = 1800,
) -> list[MemoryChunk]:
    normalized = normalize_text(body)
    if not normalized:
        return []

    parts = _split_body(normalized, max_chars=max_chars)
    meta = metadata or {}
    chunks: list[MemoryChunk] = []
    for index, part in enumerate(parts):
        chunk_key = f"{key}#{index}"
        chunks.append(
            MemoryChunk(
                chunk_id=stable_chunk_id(source, chunk_key),
                source=source,
                title=title if index == 0 else f"{title} ({index + 1})",
                content=part,
                metadata=meta,
            )
        )
    return chunks


def _split_body(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n\n")
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            parts.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        for offset in range(0, len(paragraph), max_chars):
            parts.append(paragraph[offset : offset + max_chars])
        current = ""
    if current:
        parts.append(current)
    return parts
