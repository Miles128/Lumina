"""Tests for MCP manager resilience."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secretary.agent.mcp_manager import McpManager
from secretary.services.mcp_config import McpConfigDocument, McpConfigStore, McpServerConfig


@pytest.fixture
def mcp_store(tmp_path):
    store = McpConfigStore(tmp_path / "mcp.json")
    store.save(
        McpConfigDocument(
            servers={
                "broken": McpServerConfig(command="false", args=[], enabled=True),
            }
        )
    )
    return store


def test_shutdown_survives_stack_close_error(mcp_store) -> None:
    manager = McpManager(mcp_store)
    broken_stack = AsyncMock(spec=AsyncExitStack)
    broken_stack.aclose.side_effect = RuntimeError(
        "Attempted to exit cancel scope in a different task than it was entered in"
    )
    manager._runtimes["demo"] = MagicMock(stack=broken_stack)  # type: ignore[attr-defined]

    asyncio.run_coroutine_threadsafe(manager._async_shutdown(), manager._loop).result(timeout=5)

    assert manager._runtimes == {}


def test_ensure_loaded_marks_loaded_when_reload_fails(mcp_store) -> None:
    manager = McpManager(mcp_store)

    with patch.object(manager, "_run", side_effect=RuntimeError("MCP 连接任务被取消")):
        manager.ensure_loaded()

    assert manager._loaded is True
    assert "load:" in manager.last_error
    assert manager.get_tools() == []


def test_ensure_loaded_skips_reload_when_config_unchanged(mcp_store) -> None:
    manager = McpManager(mcp_store)
    calls = {"count": 0}

    def counting_run(coro, *, timeout=180):  # noqa: ANN001
        calls["count"] += 1
        manager._bridge_tools = []
        manager._mark_connected()
        return None

    with patch.object(manager, "_run", side_effect=counting_run):
        manager.ensure_loaded()
        manager.ensure_loaded()
        manager.reload(force=False)

    assert calls["count"] == 1


def test_get_tools_never_raises(mcp_store) -> None:
    manager = McpManager(mcp_store)
    with patch.object(manager, "ensure_loaded", side_effect=RuntimeError("boom")):
        assert manager.get_tools() == []
    assert "get_tools:" in manager.last_error


def test_ensure_loaded_is_idempotent_under_concurrency(mcp_store) -> None:
    manager = McpManager(mcp_store)
    calls = {"count": 0}

    def slow_run(coro, *, timeout=180):  # noqa: ANN001
        calls["count"] += 1
        import time

        time.sleep(0.05)
        return None

    with patch.object(manager, "_run", side_effect=slow_run):
        import threading

        threads = [threading.Thread(target=manager.ensure_loaded) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

    assert calls["count"] == 1
    assert manager._loaded is True


@pytest.fixture
def mcp_manager_with_builtin(mcp_store):
    from secretary.agent.mcp_builtin import build_builtin_registry

    registry = build_builtin_registry(settings=None, sync_service=None)
    return McpManager(mcp_store, builtin_registry=registry)


def test_mcp_manager_exposes_builtin_tools(mcp_manager_with_builtin):
    """McpManager.get_tools() must include builtin provider tools."""
    tools = mcp_manager_with_builtin.get_tools()
    names = {t.name for t in tools}
    assert "mcp_feishu_status" in names
    assert "mcp_feishu_fetch" in names


def test_mcp_manager_call_builtin_tool(mcp_manager_with_builtin):
    result = mcp_manager_with_builtin.call_tool("mcp_feishu_status", {})
    assert "configured" in result


def test_mcp_manager_status_includes_builtin(mcp_manager_with_builtin):
    status = mcp_manager_with_builtin.status()
    assert status["builtin_provider_count"] >= 6
