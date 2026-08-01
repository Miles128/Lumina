"""Tests for platform settings after connector retirement."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.services.sync import SyncService


def test_platform_settings_uses_stored_health_only(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)
    start = time.time()
    cards = sync.get_stored_health()
    elapsed = time.time() - start
    assert elapsed < 1.0
    assert len(cards) == 1
    assert cards[0].source.value == "local_documents"


def test_platform_settings_endpoint_is_fast() -> None:
    client = TestClient(app)
    start = time.time()
    response = client.get("/api/settings/platforms")
    elapsed = time.time() - start
    assert response.status_code == 200
    limit = 15.0 if os.getenv("CI") else 3.0
    assert elapsed < limit


def test_get_mcp_builtin_lists_empty_providers() -> None:
    client = TestClient(app)
    resp = client.get("/api/mcp/builtin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["providers"] == []


def test_mcp_status_includes_empty_builtin_providers() -> None:
    client = TestClient(app)
    resp = client.get("/api/mcp/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["builtin_provider_count"] == 0
    assert data["builtin_providers"] == []


def test_platform_settings_endpoint_only_local_documents() -> None:
    client = TestClient(app)
    resp = client.get("/api/settings/platforms")
    assert resp.status_code == 200
    cards = resp.json()
    by_source = {card["source"]: card for card in cards}
    assert set(by_source) == {"local_documents"}
    assert by_source["local_documents"]["mcp_provider"] is False
