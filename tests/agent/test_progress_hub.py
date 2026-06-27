"""Tests for chat progress hub."""

from __future__ import annotations

import pytest

from secretary.agent.progress_events import (
    ProgressEvent,
    progress_event_label,
    progress_event_payload,
)
from secretary.agent.progress_hub import ProgressHub


@pytest.mark.asyncio
async def test_progress_hub_streams_events() -> None:
    hub = ProgressHub()
    hub.open("trace-1")
    hub.publish("trace-1", ProgressEvent(kind="iteration_started", iteration=1))
    hub.publish(
        "trace-1",
        ProgressEvent(kind="tool_started", iteration=1, tool_name="shell"),
    )
    hub.close("trace-1")

    chunks: list[str] = []
    async for chunk in hub.stream("trace-1"):
        chunks.append(chunk)

    assert any("第 1 轮思考" in chunk for chunk in chunks)
    assert any("执行命令" in chunk for chunk in chunks)
    assert any('"kind": "done"' in chunk for chunk in chunks)


def test_progress_event_label_for_web_tools_shows_network() -> None:
    started = progress_event_label(
        ProgressEvent(kind="tool_started", iteration=1, tool_name="web_search"),
    )
    finished = progress_event_label(
        ProgressEvent(kind="tool_finished", iteration=1, tool_name="web_fetch", success=True),
    )
    assert "网络连接" in started
    assert "联网搜索" in started
    assert "网络连接" in finished
    assert "抓取网页" in finished


def test_progress_event_label_for_mcp_tool() -> None:
    label = progress_event_label(
        ProgressEvent(kind="tool_started", iteration=2, tool_name="mcp_filesystem_read_file"),
    )
    assert "MCP filesystem/read_file" in label


def test_progress_event_label_for_iteration_completed() -> None:
    label = progress_event_label(
        ProgressEvent(
            kind="iteration_completed",
            iteration=2,
            message="核实通过，停止循环",
        ),
    )
    assert "核实通过" in label


def test_progress_event_payload_includes_detail() -> None:
    payload = progress_event_payload(
        ProgressEvent(
            kind="tool_finished",
            iteration=1,
            tool_name="shell",
            success=True,
            detail="ls -la\nfile.txt",
        )
    )
    assert payload["detail"] == "ls -la\nfile.txt"
