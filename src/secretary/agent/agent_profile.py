"""Primary agent profiles (OpenCode / Claude Code / Hermes patterns, Lumina runtime).

Permissions are enforced by filtering the tool list before the model sees it —
not by prompt alone (OpenCode permission ruleset).
"""

from __future__ import annotations

from enum import StrEnum

from secretary.agent.tools.base import Tool

# Claude Code: sub-agents never receive spawn_subagent (enforced in subagent/registry).
# OpenCode: primary agents differ by permission ruleset, not prompt wishful thinking.
# Hermes: orchestrator delegates; leaf sub-agents have no delegate_task.

READ_ONLY_TOOL_NAMES = frozenset(
    {
        "list_dir",
        "file_read",
        "search_files",
        "search_memory",
        "session_search",
        "web_search",
        "web_fetch",
        "shibei_search",
        "shibei_list_sources",
        "clarify",
    }
)

ORCHESTRATOR_TOOL_NAMES = frozenset(
    {
        "spawn_subagent",
        "todo",
        "clarify",
        "skills_list",
        "skill_view",
        "search_memory",
        "session_search",
        "shibei_search",
        "shibei_list_sources",
    }
)

MCP_READ_PREFIXES = ("read_", "list_", "get_")


class AgentProfile(StrEnum):
    """Primary session mode (OpenCode primary agents)."""

    BUILD = "build"
    PLAN = "plan"
    ORCHESTRATOR = "orchestrator"


PROFILE_LABELS: dict[AgentProfile, str] = {
    AgentProfile.BUILD: "Build · 执行",
    AgentProfile.PLAN: "Plan · 规划",
    AgentProfile.ORCHESTRATOR: "Orchestrator · 编排",
}


def parse_agent_profile(raw: str | None) -> AgentProfile:
    normalized = (raw or AgentProfile.BUILD.value).strip().lower()
    try:
        return AgentProfile(normalized)
    except ValueError:
        return AgentProfile.BUILD


def profile_system_appendix(profile: AgentProfile) -> str:
    if profile is AgentProfile.PLAN:
        return (
            "\n\n## Agent mode: Plan\n"
            "你只读分析、规划与审查；不要修改文件、不要执行 shell、不要委派子 Agent。"
            "输出结构化计划、风险与建议步骤；需要执行时提示用户切换到 Build 模式。"
        )
    if profile is AgentProfile.ORCHESTRATOR:
        return (
            "\n\n## Agent mode: Orchestrator\n"
            "你不直接读改写文件或跑 shell；通过 spawn_subagent 委派 explore / worker / verify。"
            "可并行 explore（goals 数组，最多 3 路）；整合子 Agent 摘要后回复用户。"
        )
    return (
        "\n\n## Agent mode: Build\n"
        "默认执行模式：可读写的工具与子 Agent 委派均可用；危险操作需用户确认。"
    )


def _is_mcp_read_tool(name: str) -> bool:
    lowered = name.lower()
    if lowered.startswith("mcp_"):
        return any(token in lowered for token in ("read", "list", "get", "search"))
    return any(lowered.startswith(prefix) for prefix in MCP_READ_PREFIXES)


def resolve_parent_tools(
    profile: AgentProfile,
    tools: list[Tool],
    *,
    spawn_tool: Tool | None,
) -> list[Tool]:
    """Filter parent-session tools by profile (OpenCode permission ruleset)."""
    by_name = {tool.name: tool for tool in tools}

    if profile is AgentProfile.BUILD:
        ordered = list(tools)
        if spawn_tool is not None and spawn_tool.name not in by_name:
            ordered.append(spawn_tool)
        return ordered

    if profile is AgentProfile.PLAN:
        picked: list[Tool] = []
        for name in sorted(READ_ONLY_TOOL_NAMES):
            if name in by_name:
                picked.append(by_name[name])
        for tool in tools:
            if tool.name not in by_name or tool in picked:
                continue
            if _is_mcp_read_tool(tool.name):
                picked.append(tool)
        return picked

    # Orchestrator: delegate-only primary (OpenCode Agent Orchestrator / Hermes orchestrator).
    picked = []
    for name in sorted(ORCHESTRATOR_TOOL_NAMES):
        if name == "spawn_subagent":
            continue
        if name in by_name:
            picked.append(by_name[name])
    if spawn_tool is not None:
        picked.append(spawn_tool)
    return picked


def default_max_steps_for_profile(profile: AgentProfile, *, filesystem_turn: bool) -> int:
    if profile is AgentProfile.ORCHESTRATOR:
        return 12
    if profile is AgentProfile.PLAN:
        return 6
    if filesystem_turn:
        return 8
    return 8
