"""Harness cancel / SessionStore prune / MCP remote wiring."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from secretary.agent.llm_config import LlmConfig
from secretary.agent.session_store import SessionStore, pause_restore_parent
from secretary.agent.tools.shell import ShellTool
from secretary.agent.turn_cancel import begin_turn, end_turn, is_cancelled, request_cancel
from secretary.services.mcp_config import McpServerConfig


def test_confirm_path_registers_cancel_event() -> None:
    event = begin_turn("confirm-trace")
    assert event.is_set() is False
    assert request_cancel("confirm-trace") is True
    assert is_cancelled("confirm-trace") is True
    end_turn("confirm-trace")
    assert request_cancel("confirm-trace") is False


def test_shell_tool_cancels_mid_command(tmp_path: Path) -> None:
    tool = ShellTool()
    tool.bind_cancel_check(lambda: True)
    result = tool.execute({"command": "sleep 30", "timeout": 30}, tmp_path)
    assert not isinstance(result, str)
    assert result.error is not None
    assert "cancel" in result.error.lower() or "取消" in result.error


def test_session_store_prune_keeps_paused_and_drops_old(tmp_path: Path) -> None:
    path = tmp_path / "turns.json"
    store = SessionStore(persistence_path=path)
    old = store.start_turn(trace_id="old", user_message="x")
    old.status = "completed"
    old.started_at = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
    store._save_turn(old)

    fresh = store.start_turn(trace_id="fresh", user_message="y")
    fresh.status = "completed"
    store._save_turn(fresh)

    paused = store.start_turn(trace_id="paused", user_message="z")
    paused.status = "paused"
    paused.started_at = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
    store._save_turn(paused)
    store.save_pause("paused", kind="confirmation", data={"pending": {}})

    removed = store.prune_stale(max_age_hours=72, max_turns=200)
    assert removed >= 1
    doc = store._load_document()
    assert "old" not in doc["turns"]
    assert "paused" in doc["turns"]
    assert "fresh" in doc["turns"]


def test_pause_restore_parent_fails_loud_on_missing_tools() -> None:
    data = {
        "tool_names": ["shell", "missing_tool"],
        "messages_snapshot": [],
        "max_steps": 5,
        "pending_step": {
            "thought": "t",
            "tool_call": {"name": "shell", "arguments": {}},
            "tool_result": "",
            "reply": "",
        },
        "native_used": False,
        "step_idx": 1,
    }
    with pytest.raises(ValueError, match="missing"):
        pause_restore_parent(
            data,
            llm_config=LlmConfig(
                api_key="k",
                base_url="https://example.com",
                model="m",
                source="test",
            ),
            tools=[],
        )


def test_mcp_connect_remote_streamable_http() -> None:
    from secretary.agent.mcp_manager import McpManager
    from secretary.services.mcp_config import McpConfigStore

    manager = McpManager(McpConfigStore(Path("/tmp/unused-mcp.json")))
    with patch("secretary.agent.mcp_manager.streamable_http_client") as client_cm:
        enter = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
        client_cm.return_value.__aenter__ = enter
        client_cm.return_value.__aexit__ = AsyncMock(return_value=None)
        with patch.object(manager, "_register_session", AsyncMock()) as reg:
            asyncio.run(
                manager._connect_remote(
                    "remote",
                    McpServerConfig(
                        url="https://example.com/mcp",
                        transport="streamable_http",
                        headers={"Authorization": "Bearer x"},
                    ),
                )
            )
            assert reg.await_count == 1
            assert client_cm.called
