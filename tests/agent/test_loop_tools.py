"""Tests for agent memory and session search tools."""

from pathlib import Path

from secretary.agent.tools.memory_tools import MemoryTool, SessionSearchTool
from secretary.memory.hermes_memory import HermesMemory


def test_memory_tool_add(tmp_path: Path) -> None:
    hermes = HermesMemory(tmp_path)
    tool = MemoryTool(hermes)
    output = tool.execute(
        {"action": "add", "target": "user", "text": "Timezone: Asia/Shanghai"},
        tmp_path,
    )
    assert "Asia/Shanghai" in hermes.read_user_md()
    assert output


def test_session_search_tool_finds_message(tmp_path: Path) -> None:
    hermes = HermesMemory(tmp_path)
    hermes.create_session("sess-1")
    hermes.add_message("sess-1", "user", "上周讨论了飞书日程同步")
    hermes.add_message("sess-1", "assistant", "好的，已记录")

    tool = SessionSearchTool(hermes)
    output = tool.execute({"query": "飞书日程", "limit": 5}, tmp_path)
    assert "飞书日程" in output
