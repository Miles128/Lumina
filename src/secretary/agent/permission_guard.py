"""Hard tool permission guard for primary agent profiles."""

from __future__ import annotations

from secretary.agent.agent_profile import AgentProfile
from secretary.agent.tools.base import Tool

PLAN_DENY_TOOL_NAMES = frozenset(
    {
        "file_write",
        "patch",
        "file_delete",
        "shell",
        "sync_source",
        "shibei_import",
        "memory",
        "spawn_subagent",
        "spawn_cli_agent",
    }
)

PLAN_DENY_NAME_TOKENS = ("write", "delete", "remove", "shell", "sync", "import", "spawn", "cli")


def tool_allowed_for_profile(profile: AgentProfile, tool: Tool) -> bool:
    if profile is not AgentProfile.PLAN:
        return True
    name = tool.name.lower()
    if name in PLAN_DENY_TOOL_NAMES:
        return False
    if getattr(tool, "needs_confirmation", False):
        return False
    if name.startswith("mcp_"):
        from secretary.agent.mcp_manager import mcp_tool_needs_confirmation

        return not mcp_tool_needs_confirmation(name)
    name_tokens = name.replace("-", "_").split("_")
    if any(token in name_tokens for token in PLAN_DENY_NAME_TOKENS):
        return False
    return True


def guard_tools_for_profile(profile: AgentProfile, tools: list[Tool]) -> list[Tool]:
    return [tool for tool in tools if tool_allowed_for_profile(profile, tool)]
