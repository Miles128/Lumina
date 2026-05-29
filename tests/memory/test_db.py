"""Tests for memory store."""

from pathlib import Path

from secretary.core.types import ConnectorHealth, ConnectorStatus, MemoryChunk, SourceKind
from secretary.memory.db import MemoryStore


def test_memory_store_roundtrip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    chunk = MemoryChunk(
        chunk_id="abc",
        source=SourceKind.FEISHU,
        title="飞书日程",
        content="明天 10:00 产品评审",
        metadata={"kind": "calendar"},
    )
    inserted = store.upsert_chunks([chunk])
    assert inserted == 1

    results = store.search("产品", limit=5)
    assert len(results) == 1
    assert results[0].title == "飞书日程"


def test_sync_state_persistence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    health = ConnectorHealth(
        source=SourceKind.EMAIL,
        status=ConnectorStatus.READY,
        message="ok",
        item_count=3,
    )
    store.update_sync_state(health)
    states = store.get_sync_states()
    assert len(states) == 1
    assert states[0].source is SourceKind.EMAIL
    assert states[0].item_count == 3


def test_search_with_backticks_does_not_crash(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    chunk = MemoryChunk(
        chunk_id="shell-1",
        source=SourceKind.FEISHU,
        title="执行命令",
        content="请调用 shell 执行 pwd",
        metadata={"kind": "note"},
    )
    store.upsert_chunks([chunk])
    results = store.search("请调用 shell 执行 `pwd`", limit=5)
    assert len(results) == 1
    assert results[0].chunk_id == "shell-1"
