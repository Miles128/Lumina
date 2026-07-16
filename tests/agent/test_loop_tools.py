"""Tests for agent memory and session search tools."""

from pathlib import Path

from secretary.agent.tools.base import Tool, ToolResult
from secretary.agent.tools.memory_tools import MemoryTool, SessionSearchTool
from secretary.memory.lumina_memory import LuminaMemory


def test_memory_tool_add_to_memory_target(tmp_path: Path) -> None:
    """MemoryTool 只支持 target=memory；target=user 应返回 failure。"""
    memory = LuminaMemory(tmp_path)
    tool = MemoryTool(memory)
    output = tool.execute(
        {"action": "add", "target": "memory", "text": "Timezone: Asia/Shanghai"},
        tmp_path,
    )
    assert "Asia/Shanghai" in memory.read_memory_md()
    assert output


def test_memory_tool_rejects_user_target(tmp_path: Path) -> None:
    """target=user 已退役，MemoryTool 应返回 ToolResult.failure。"""
    memory = LuminaMemory(tmp_path)
    tool = MemoryTool(memory)
    output = tool.execute(
        {"action": "add", "target": "user", "text": "Name: Alex"},
        tmp_path,
    )
    # mutate_memory 抛 ValueError → MemoryTool.execute 捕获并返回 ToolResult.failure
    assert isinstance(output, ToolResult) or "error" in str(output).lower()
    # 不应有任何 USER.md 被写入
    assert not (tmp_path / "memories" / "USER.md").exists()


def test_session_search_tool_finds_message(tmp_path: Path) -> None:
    memory = LuminaMemory(tmp_path)
    memory.create_session("sess-1")
    memory.add_message("sess-1", "user", "上周讨论了飞书日程同步")
    memory.add_message("sess-1", "assistant", "好的，已记录")

    tool = SessionSearchTool(memory)
    output = tool.execute({"query": "飞书日程", "limit": 5}, tmp_path)
    assert "飞书日程" in output
