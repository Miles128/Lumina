"""Tests for primary agent profiles (OpenCode permission ruleset)."""

from __future__ import annotations

from secretary.agent.agent_profile import (
    AgentProfile,
    parse_agent_profile,
    resolve_parent_tools,
)
from secretary.agent.p0_tools import ClarifyTool, SkillsListTool
from secretary.agent.skills import SkillManager
from secretary.agent.tools.fs import FileReadTool, FileWriteTool, ListDirTool
from secretary.agent.tools.shell import ShellTool


class _SpawnStub:
    name = "spawn_subagent"


def test_parse_agent_profile_defaults_to_build() -> None:
    assert parse_agent_profile(None) is AgentProfile.BUILD
    assert parse_agent_profile("unknown") is AgentProfile.BUILD
    assert parse_agent_profile("orchestrator") is AgentProfile.ORCHESTRATOR


def test_plan_profile_filters_to_read_only_tools() -> None:
    tools = [
        ListDirTool(),
        FileReadTool(),
        FileWriteTool(),
        ShellTool(),
        ClarifyTool(),
    ]
    picked = resolve_parent_tools(AgentProfile.PLAN, tools, spawn_tool=_SpawnStub())
    names = {tool.name for tool in picked}
    assert names <= {"list_dir", "file_read", "clarify"}
    assert "spawn_subagent" not in names
    assert "shell" not in names


def test_orchestrator_profile_is_delegate_only(tmp_path) -> None:
    tools = [
        ListDirTool(),
        FileWriteTool(),
        ShellTool(),
        SkillsListTool(SkillManager(tmp_path)),
        ClarifyTool(),
    ]
    picked = resolve_parent_tools(AgentProfile.ORCHESTRATOR, tools, spawn_tool=_SpawnStub())
    names = {tool.name for tool in picked}
    assert "spawn_subagent" in names
    assert "skills_list" in names
    assert "list_dir" not in names
    assert "shell" not in names


def test_build_profile_keeps_tools_and_spawn() -> None:
    tools = [ListDirTool(), FileReadTool()]
    picked = resolve_parent_tools(AgentProfile.BUILD, tools, spawn_tool=_SpawnStub())
    names = {tool.name for tool in picked}
    assert names == {"list_dir", "file_read", "spawn_subagent"}
