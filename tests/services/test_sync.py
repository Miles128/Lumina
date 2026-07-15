"""Tests for SyncService routing through MCP builtin fetch tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.agent.mcp_builtin import build_builtin_registry
from secretary.agent.mcp_manager import McpManager
from secretary.config import Settings
from secretary.core.types import SourceKind
from secretary.memory.db import MemoryStore
from secretary.services.mcp_config import McpConfigStore
from secretary.services.sync import SyncService


@pytest.fixture
def sync_service_with_mcp(tmp_path: Path) -> SyncService:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    registry = build_builtin_registry(settings=None, sync_service=None)
    mcp_store = McpConfigStore(tmp_path / "mcp.json")
    mcp_manager = McpManager(mcp_store, builtin_registry=registry)
    return SyncService(settings, store, mcp_manager=mcp_manager)


def test_sync_source_calls_mcp_fetch(monkeypatch, sync_service_with_mcp) -> None:
    """sync_source(feishu) must call mcp_feishu_fetch and upsert returned chunks."""
    calls: list[str] = []

    def fake_call_tool(name, args, timeout=None):  # noqa: ANN001
        calls.append(name)
        if name == "mcp_feishu_fetch":
            return {
                "source": "feishu",
                "count": 1,
                "chunks": [
                    {
                        "chunk_id": "feishu-test-1",
                        "source": "feishu",
                        "title": "测试日程",
                        "content": "测试内容",
                        "metadata": {},
                    }
                ],
            }
        return {"error": "unknown"}

    monkeypatch.setattr(sync_service_with_mcp._mcp_manager, "call_tool", fake_call_tool)
    result = sync_service_with_mcp.sync_source(SourceKind.FEISHU)
    assert "mcp_feishu_fetch" in calls
    assert result.inserted >= 1
