"""Tests for browser connector sync gating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from secretary.config import Settings
from secretary.connectors.weread import WeReadConnector
from secretary.core.types import SourceKind
from secretary.memory.db import MemoryStore
from secretary.services.sync import SyncService


def test_sync_all_skips_browser_sources_by_default(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)

    weread = MagicMock(spec=WeReadConnector)
    weread.source = SourceKind.WEREAD
    weread.is_configured.return_value = True
    weread.fetch.return_value = []

    with patch.object(sync, "_connectors", [weread]):
        with patch.object(sync, "sync_source", wraps=sync.sync_source) as spy:
            with patch.object(sync, "_sync_local_documents", return_value=MagicMock(inserted=0)):
                sync.sync_all(include_browser_sources=False)

    assert not any(call.args[0] == SourceKind.WEREAD for call in spy.call_args_list)


def test_sync_all_includes_browser_sources_when_requested(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)

    weread = MagicMock(spec=WeReadConnector)
    weread.source = SourceKind.WEREAD
    weread.is_configured.return_value = True
    weread.fetch.return_value = []

    with patch.object(sync, "_connectors", [weread]):
        with patch.object(sync, "sync_source", wraps=sync.sync_source) as spy:
            with patch.object(sync, "_sync_local_documents", return_value=MagicMock(inserted=0)):
                sync.sync_all(include_browser_sources=True)

    assert any(call.args[0] == SourceKind.WEREAD for call in spy.call_args_list)
