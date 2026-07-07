"""Tests for primary agent profiles (Build / Ask / Plan)."""

from __future__ import annotations

from secretary.agent.agent_profile import (
    AgentProfile,
    effective_profile,
    parse_agent_profile,
    resolve_auto_profile,
    resolve_parent_tools,
)
from secretary.agent.p0_tools import AskUserTool, ClarifyTool, SkillsListTool, TodoTool
from secretary.agent.skills import SkillManager
from secretary.agent.tools.fs import FileReadTool, FileWriteTool, ListDirTool
from secretary.agent.tools.shell import ShellTool
from secretary.services.todo_store import TodoStore


class _SpawnStub:
    name = "spawn_subagent"


class _CliSpawnStub:
    name = "spawn_cli_agent"


def test_parse_agent_profile_defaults_to_auto() -> None:
    assert parse_agent_profile(None) is AgentProfile.AUTO
    assert parse_agent_profile("unknown") is AgentProfile.AUTO
    assert parse_agent_profile("ask") is AgentProfile.ASK
    assert parse_agent_profile("auto") is AgentProfile.AUTO
    assert parse_agent_profile("orchestrator") is AgentProfile.BUILD


def test_resolve_auto_profile_picks_plan_and_build() -> None:
    assert resolve_auto_profile("帮我规划一下重构步骤") is AgentProfile.PLAN
    assert resolve_auto_profile("把 README 改一下并运行测试") is AgentProfile.BUILD
    assert resolve_auto_profile("读取记忆：面试") is AgentProfile.ASK


def test_effective_profile_passthrough_non_auto() -> None:
    assert effective_profile(AgentProfile.PLAN, "写文件") is AgentProfile.PLAN


def test_ask_profile_filters_to_read_only_tools(tmp_path) -> None:
    tools = [
        ListDirTool(),
        FileReadTool(),
        FileWriteTool(),
        ShellTool(),
        ClarifyTool(),
        AskUserTool(),
        TodoTool(TodoStore(tmp_path / "todo.json")),
    ]
    picked = resolve_parent_tools(AgentProfile.ASK, tools, spawn_tool=_SpawnStub())
    names = {tool.name for tool in picked}
    assert "list_dir" in names
    assert "ask_user" in names
    assert "spawn_subagent" not in names
    assert "shell" not in names
    assert "todo" not in names


def test_plan_profile_includes_todo_and_skills(tmp_path) -> None:
    tools = [
        ListDirTool(),
        FileWriteTool(),
        ClarifyTool(),
        TodoTool(TodoStore(tmp_path / "todo.json")),
        SkillsListTool(SkillManager(tmp_path)),
    ]
    picked = resolve_parent_tools(AgentProfile.PLAN, tools, spawn_tool=_SpawnStub())
    names = {tool.name for tool in picked}
    assert "todo" in names
    assert "skills_list" in names
    assert "file_write" not in names
    assert "spawn_subagent" not in names


def test_build_profile_keeps_tools_and_spawn() -> None:
    tools = [ListDirTool(), FileReadTool()]
    picked = resolve_parent_tools(
        AgentProfile.BUILD,
        tools,
        spawn_tool=_SpawnStub(),
        cli_spawn_tool=_CliSpawnStub(),
    )
    names = {tool.name for tool in picked}
    assert names == {"list_dir", "file_read", "spawn_subagent", "spawn_cli_agent"}
