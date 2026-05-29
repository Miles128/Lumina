"""Tests for local documents memory indexing."""

from pathlib import Path

from secretary.config import Settings
from secretary.core.types import SourceKind
from secretary.memory.db import MemoryStore
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.services.sync import SyncService


def test_local_documents_sync_writes_memory(tmp_path: Path) -> None:
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "简历.md").write_text("我叫测试用户，擅长 Python。", encoding="utf-8")

    settings = Settings(
        data_dir=tmp_path / "data",
        local_documents_enabled=True,
        local_documents_path=str(docs),
        local_documents_max_files=10,
    )
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)
    result = sync.sync_source(SourceKind.LOCAL_DOCUMENTS)

    assert result.inserted >= 1
    chunks = store.list_by_source(SourceKind.LOCAL_DOCUMENTS, limit=10)
    assert chunks
    assert any("Python" in chunk.content for chunk in chunks)


def test_memory_chunks_from_profile(tmp_path: Path) -> None:
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "随笔.md").write_text("今天整理了知识库。", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data",
        local_documents_enabled=True,
        local_documents_path=str(docs),
    )
    profiler = LocalDocumentsProfiler(settings)
    profile = profiler.analyze_and_save()
    chunks = profiler.memory_chunks(profile)
    assert chunks
    assert chunks[0].source is SourceKind.LOCAL_DOCUMENTS
