"""Tests for memory ingest helpers."""

from secretary.core.types import SourceKind
from secretary.memory.ingest import chunk_text, normalize_text, stable_chunk_id


def test_stable_chunk_id_is_deterministic() -> None:
    first = stable_chunk_id(SourceKind.EMAIL, "hello")
    second = stable_chunk_id(SourceKind.EMAIL, "hello")
    assert first == second


def test_chunk_text_splits_long_body() -> None:
    body = "段落\n\n" + ("内容" * 900)
    chunks = chunk_text(
        source=SourceKind.WEREAD,
        key="book-1",
        title="测试书",
        body=body,
        max_chars=200,
    )
    assert len(chunks) > 1
    assert all(chunk.source is SourceKind.WEREAD for chunk in chunks)


def test_normalize_text_collapses_blank_lines() -> None:
    assert normalize_text("a\n\n\n\nb") == "a\n\nb"
