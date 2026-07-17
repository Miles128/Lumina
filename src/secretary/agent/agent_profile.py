"""Primary agent profiles (Build / Ask / Plan)."""

from __future__ import annotations

from enum import StrEnum

from secretary.agent.tools.base import Tool

# Claude Code: sub-agents never receive spawn_subagent (enforced in subagent/registry).

ASK_TOOL_NAMES = frozenset(
    {
        "list_dir",
        "file_read",
        "read_document",
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
        "emit_card",
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

    AUTO = "auto"
    BUILD = "build"
    ASK = "ask"
    PLAN = "plan"


PROFILE_LABELS: dict[AgentProfile, str] = {
    AgentProfile.AUTO: "Auto · 自动",
    AgentProfile.BUILD: "Build · 执行",
    AgentProfile.ASK: "Ask · 问答",
    AgentProfile.PLAN: "Plan · 规划",
}

_PLAN_MARKERS = (
    "规划",
    "方案",
    "计划",
    "步骤",
    "roadmap",
    "架构",
    "设计一下",
    "怎么实现",
    "如何实现",
    "拆解",
    "里程碑",
)

_BUILD_MARKERS = (
    "写",
    "改",
    "删",
    "创建",
    "运行",
    "执行",
    "同步",
    "部署",
    "fix",
    "bug",
    "修复",
    "shell",
    "命令",
    "安装",
    "构建",
    "build",
    "patch",
    "refactor",
    "重构",
    "提交",
    "git commit",
    "spawn",
    "委派",
)

_ASK_MARKERS = (
    "是什么",
    "什么是",
    "解释",
    "介绍",
    "总结",
    "查询",
    "查一下",
    "读取",
    "读取记忆",
    "搜索",
    "有哪些",
    "告诉我",
)


def parse_agent_profile(raw: str | None) -> AgentProfile:
    normalized = (raw or AgentProfile.AUTO.value).strip().lower()
    try:
        return AgentProfile(normalized)
    except ValueError:
        return AgentProfile.AUTO


def resolve_auto_profile(
    user_message: str,
    *,
    light_mode: bool = False,
    filesystem_turn: bool = False,
) -> AgentProfile:
    """Pick ask/plan/build for Auto mode using rules (no extra LLM call)."""
    text = user_message.strip().lower()
    if not text:
        return AgentProfile.ASK
    if light_mode and not filesystem_turn:
        return AgentProfile.ASK
    plan_hit = any(marker in text for marker in _PLAN_MARKERS)
    build_hit = any(marker in text for marker in _BUILD_MARKERS)
    ask_hit = any(marker in text for marker in _ASK_MARKERS)
    if plan_hit and build_hit and any(marker in text for marker in ("规划", "方案", "步骤", "计划")):
        return AgentProfile.PLAN
    if build_hit or filesystem_turn:
        return AgentProfile.BUILD
    if plan_hit:
        return AgentProfile.PLAN
    if ask_hit:
        return AgentProfile.ASK
    return AgentProfile.ASK


def effective_profile(
    profile: AgentProfile,
    user_message: str,
    *,
    light_mode: bool = False,
    filesystem_turn: bool = False,
) -> AgentProfile:
    if profile is AgentProfile.AUTO:
        return resolve_auto_profile(
            user_message,
            light_mode=light_mode,
            filesystem_turn=filesystem_turn,
        )
    return profile


def profile_system_appendix(profile: AgentProfile) -> str:
    if profile is AgentProfile.AUTO:
        return (
            "\n\n## Agent mode: Auto\n"
            "系统已根据本轮问题自动选择工具边界；只读检索优先 Ask，规划类走 Plan，"
            "写盘/shell/同步/委派仅在 Build 语义下启用。"
        )
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
        "执行模式：读写、shell、同步连接器、子 Agent 均可用；危险操作需用户确认。"
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

    def _append_spawn_tools(ordered: list[Tool]) -> list[Tool]:
        names = {tool.name for tool in ordered}
        if spawn_tool is not None and spawn_tool.name not in names:
            ordered.append(spawn_tool)
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
    """Upper bound only — the loop returns as soon as a satisfactory reply is ready."""
    if profile is AgentProfile.ASK:
        return 20
    if profile is AgentProfile.PLAN:
        return 20
    if filesystem_turn:
        return 20
    return 20
