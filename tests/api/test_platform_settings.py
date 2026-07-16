"""Tests for fast platform settings loading."""

from __future__ import annotations

import os
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
    # CI runners cold-start the full FastAPI app (MCP, connectors); allow more headroom.
    limit = 15.0 if os.getenv("CI") else 3.0
    assert elapsed < limit


def test_get_mcp_builtin_lists_providers() -> None:
    client = TestClient(app)
    resp = client.get("/api/mcp/builtin")
    assert resp.status_code == 200
    data = resp.json()
    names = {p["name"] for p in data["providers"]}
    assert "feishu" in names
    assert "email" in names
    for p in data["providers"]:
        assert "display_name" in p
        assert "configured" in p
        assert "status" in p
        assert "message" in p
        assert "item_count" in p
        assert "last_sync_at" in p


def test_mcp_status_includes_builtin_providers() -> None:
    client = TestClient(app)
    resp = client.get("/api/mcp/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "builtin_provider_count" in data
    assert isinstance(data["builtin_provider_count"], int)
    assert data["builtin_provider_count"] >= 1
    assert "builtin_providers" in data
    assert isinstance(data["builtin_providers"], list)
    assert len(data["builtin_providers"]) == data["builtin_provider_count"]
    names = {p["name"] for p in data["builtin_providers"]}
    assert "feishu" in names
    for p in data["builtin_providers"]:
        assert "display_name" in p
        assert "configured" in p
        assert "status" in p


def test_platform_settings_endpoint_exposes_mcp_provider_flag() -> None:
    client = TestClient(app)
    resp = client.get("/api/settings/platforms")
    assert resp.status_code == 200
    cards = resp.json()
    by_source = {card["source"]: card for card in cards}

    # 6 个 connector 平台应标记为 mcp_provider=True
    mcp_sources = {
        "feishu",
        "email",
        "weread",
        "xiaohongshu",
        "weixin_oa",
        "cloud_drive",
    }
    for source in mcp_sources:
        assert source in by_source, f"missing platform card: {source}"
        card = by_source[source]
        assert "mcp_provider" in card, f"{source} card missing mcp_provider field"
        assert card["mcp_provider"] is True, (
            f"{source} should be marked mcp_provider=True"
        )

    # LOCAL_DOCUMENTS 不应标记为 mcp_provider
    assert "local_documents" in by_source
    assert by_source["local_documents"]["mcp_provider"] is False, (
        "local_documents should not be marked as mcp_provider"
    )
