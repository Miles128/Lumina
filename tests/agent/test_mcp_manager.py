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
