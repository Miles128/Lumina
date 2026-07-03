"""Primary agent profiles (Build / Ask / Plan)."""

from __future__ import annotations

from enum import StrEnum

from secretary.agent.tools.base import Tool

# Claude Code: sub-agents never receive spawn_subagent (enforced in subagent/registry).

ASK_TOOL_NAMES = frozenset(
    {
        "list_dir",
        "file_read",
        "search_files",
        "glob_files",
        "search_memory",
        "session_search",
        "web_search",
        "web_fetch",
        "shibei_search",
        "shibei_list_sources",
        "list_connectors",
        "connector_status",
        "clarify",
        "ask_user",
        "browser_open",
        "browser_snapshot",
        "browser_screenshot",
        "browser_click",
        "browser_fill",
        "browser_close",
    }
)

PLAN_TOOL_NAMES = ASK_TOOL_NAMES | frozenset(
    {
        "todo",
        "skills_list",
        "skill_view",
    }
)

MCP_READ_PREFIXES = ("read_", "list_", "get_")


class AgentProfile(StrEnum):
    """Primary session mode."""

    BUILD = "build"
    ASK = "ask"
    PLAN = "plan"


PROFILE_LABELS: dict[AgentProfile, str] = {
    AgentProfile.BUILD: "Build · 执行",
    AgentProfile.ASK: "Ask · 问答",
    AgentProfile.PLAN: "Plan · 规划",
}


def parse_agent_profile(raw: str | None) -> AgentProfile:
    normalized = (raw or AgentProfile.BUILD.value).strip().lower()
    if normalized == "orchestrator":
        return AgentProfile.BUILD
    try:
        return AgentProfile(normalized)
    except ValueError:
        return AgentProfile.BUILD


def profile_system_appendix(profile: AgentProfile) -> str:
    if profile is AgentProfile.ASK:
        return (
            "\n\n## Agent mode: Ask\n"
            "问答与检索模式：可读文件、搜记忆/Shibei、联网与浏览器只读操作；"
            "不要修改文件、不要执行 shell、不要委派子 Agent。"
            "缺信息时用 ask_user 结构化追问。"
        )
    if profile is AgentProfile.PLAN:
        return (
            "\n\n## Agent mode: Plan\n"
            "规划模式：只读分析 + todo/skills；输出结构化计划、风险与步骤；"
            "不要修改文件、不要 shell、不要委派。需要执行时提示切换到 Build。"
        )
    return (
        "\n\n## Agent mode: Build\n"
        "执行模式：读写、shell、同步连接器、子 Agent 与 CLI 委派均可用；危险操作需用户确认。"
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
    cli_spawn_tool: Tool | None = None,
) -> list[Tool]:
    """Filter parent-session tools by profile (OpenCode permission ruleset)."""
    by_name = {tool.name: tool for tool in tools}

    def _append_spawn_tools(ordered: list[Tool]) -> list[Tool]:
        names = {tool.name for tool in ordered}
        if spawn_tool is not None and spawn_tool.name not in names:
            ordered.append(spawn_tool)
        if cli_spawn_tool is not None and cli_spawn_tool.name not in names:
            ordered.append(cli_spawn_tool)
        return ordered

    if profile is AgentProfile.BUILD:
        return _append_spawn_tools(list(tools))

    allowed = PLAN_TOOL_NAMES if profile is AgentProfile.PLAN else ASK_TOOL_NAMES
    picked: list[Tool] = []
    for name in sorted(allowed):
        if name in by_name:
            picked.append(by_name[name])
    for tool in tools:
        if tool.name in by_name and tool not in picked and _is_mcp_read_tool(tool.name):
            picked.append(tool)
    return picked


def default_max_steps_for_profile(profile: AgentProfile, *, filesystem_turn: bool) -> int:
    if profile is AgentProfile.ASK:
        return 6
    if profile is AgentProfile.PLAN:
        return 8
    if filesystem_turn:
        return 8
    return 8
