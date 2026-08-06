"""Tests for SyncService after platform connector retirement."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.config import Settings
from secretary.core.types import ConnectorStatus, SourceKind
from secretary.memory.db import MemoryStore
from secretary.services.sync import SyncService


@pytest.fixture
def sync_service(tmp_path: Path) -> SyncService:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    return SyncService(settings, store)


def test_sync_source_platform_connectors_retired(sync_service: SyncService) -> None:
    result = sync_service.sync_source(SourceKind.FEISHU)
    assert result.inserted == 0
    assert result.health.status is ConnectorStatus.NOT_CONFIGURED
    assert "连接器已移除" in result.health.message


def test_sync_all_only_local_documents(sync_service: SyncService) -> None:
    results = sync_service.sync_all()
    assert len(results) == 1
    assert results[0].source is SourceKind.LOCAL_DOCUMENTS


def test_get_stored_health_only_local_documents(sync_service: SyncService) -> None:
    health = sync_service.get_stored_health()
    assert len(health) == 1
    assert health[0].source is SourceKind.LOCAL_DOCUMENTS
