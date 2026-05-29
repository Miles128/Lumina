"""Tests for purging indexed local document chunks."""

from pathlib import Path

from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.db import MemoryStore


def test_purge_source_removes_chunks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.upsert_chunks(
        [
            MemoryChunk(
                chunk_id="old-doc",
                source=SourceKind.LOCAL_DOCUMENTS,
                title="旧索引",
                content="should be removed",
            ),
        ]
    )
    removed = store.purge_source(SourceKind.LOCAL_DOCUMENTS)
    assert removed == 1
    assert store.list_by_source(SourceKind.LOCAL_DOCUMENTS) == []
