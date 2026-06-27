"""Tests for sync empty-state routing (PRD v0.1.1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from secretary.agent.sync_routing import (
    detect_memory_sources,
    resolve_sync_empty_reply,
)
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
from secretary.memory.db import MemoryStore


def test_detect_memory_sources_weread() -> None:
    sources = detect_memory_sources("我微信读书最近在读什么")
    assert SourceKind.WEREAD in sources


def test_resolve_sync_empty_for_weread_without_data(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    sync = MagicMock()
    sync.get_stored_health.return_value = [
        ConnectorHealth(
            source=SourceKind.WEREAD,
            status=ConnectorStatus.READY,
            message="ok",
            item_count=0,
        )
    ]
    reply = resolve_sync_empty_reply(
        "我微信读书读过哪些书",
        store,
        sync,
        memory_hits=0,
    )
    assert reply is not None
    assert "同步" in reply
    assert "编造" in reply or "微信读书" in reply


def test_resolve_sync_empty_skips_when_weread_has_data(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from secretary.core.types import MemoryChunk

    store = MemoryStore(tmp_path / "memory.db")
    store.upsert_chunks(
        [
            MemoryChunk(
                chunk_id="w1",
                source=SourceKind.WEREAD,
                title="Deep Work",
                content="focus book",
                created_at=datetime.now(UTC),
            )
        ]
    )
    reply = resolve_sync_empty_reply(
        "微信读书书架",
        store,
        None,
        memory_hits=0,
    )
    assert reply is None


def test_resolve_sync_empty_generic_personal(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    reply = resolve_sync_empty_reply(
        "根据我的记忆总结一下",
        store,
        None,
        memory_hits=0,
    )
    assert reply is not None
    assert "同步" in reply


def test_resolve_sync_empty_skips_memory_write(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    reply = resolve_sync_empty_reply(
        "写入记忆：我喜欢用 Python",
        store,
        None,
        memory_hits=0,
    )
    assert reply is None


def test_resolve_sync_empty_skips_when_shibei_ready(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    shibei = MagicMock()
    shibei.is_enabled.return_value = True
    shibei.is_available.return_value = True
    shibei.status_view.return_value = {
        "status": "ready",
        "sources": ["/notes"],
        "source_count": 46,
    }
    reply = resolve_sync_empty_reply(
        "根据我的记忆总结一下",
        store,
        None,
        memory_hits=0,
        shibei_service=shibei,
    )
    assert reply is None


def test_resolve_sync_empty_weread_skips_when_shibei_ready(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    sync = MagicMock()
    sync.get_stored_health.return_value = [
        ConnectorHealth(
            source=SourceKind.WEREAD,
            status=ConnectorStatus.READY,
            message="ok",
            item_count=0,
        )
    ]
    shibei = MagicMock()
    shibei.is_enabled.return_value = True
    shibei.is_available.return_value = True
    shibei.status_view.return_value = {
        "status": "ready",
        "sources": ["/notes"],
    }
    reply = resolve_sync_empty_reply(
        "我微信读书读过哪些书",
        store,
        sync,
        memory_hits=0,
        shibei_service=shibei,
    )
    assert reply is None
