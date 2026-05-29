"""Tests for fast platform settings loading."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.config import Settings
from secretary.connectors.feishu import FeishuConnector
from secretary.memory.db import MemoryStore
from secretary.services.sync import SyncService


def test_platform_settings_uses_stored_health_only(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)

    def slow_health() -> object:
        time.sleep(5)
        raise AssertionError("live connector.health should not run for settings")

    with patch.object(FeishuConnector, "health", slow_health):
        sync.reload_connectors()
        start = time.time()
        cards = sync.get_stored_health()
        elapsed = time.time() - start

    assert elapsed < 1.0
    assert len(cards) >= 7


def test_platform_settings_endpoint_is_fast() -> None:
    client = TestClient(app)
    start = time.time()
    response = client.get("/api/settings/platforms")
    elapsed = time.time() - start
    assert response.status_code == 200
    assert elapsed < 3.0
