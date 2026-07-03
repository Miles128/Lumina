"""Structured progress events for agent loop instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from secretary.agent.turn_models import PROGRESS_SCHEMA_VERSION

ProgressKind = Literal[
    "turn_started",
    "turn_completed",
    "pause_confirmation",
    "iteration_started",
    "iteration_completed",
    "tool_started",
    "tool_finished",
    "subagent_started",
    "subagent_paused",
    "subagent_finished",
    "cli_agent_started",
    "cli_agent_finished",
    "final_reply",
    "stopped",
    "reply_start",
    "reply_delta",
    "reply_end",
]


@dataclass(frozen=True)
class ProgressEvent:
    kind: ProgressKind
    iteration: int
    message: str = ""
    tool_name: str = ""
    success: bool = True
    detail: str = ""
    sub_run_id: str = ""
    archetype: str = ""
    goal: str = ""
    subagent_status: str = ""
    parent_sub_run_id: str = ""
    turn_id: str = ""
    thread_id: str = ""
    item_id: str = ""
    parent_turn_id: str = ""


_TOOL_LABELS: dict[str, str] = {
    "list_dir": "浏览目录",
    "file_read": "读取文件",
    "file_write": "写入文件",
    "file_delete": "删除文件",
    "search_files": "搜索文件",
    "glob_files": "查找文件",
    "shell": "执行命令",
    "search_memory": "搜索记忆",
    "session_search": "搜索会话",
    "web_search": "联网搜索",
    "web_fetch": "抓取网页",
    "browser_open": "打开网页",
    "browser_snapshot": "浏览器快照",
    "browser_screenshot": "浏览器截图",
    "browser_click": "浏览器点击",
    "browser_fill": "浏览器填写",
    "browser_close": "关闭浏览器",
    "list_connectors": "连接器列表",
    "connector_status": "连接器状态",
    "sync_source": "同步数据源",
    "shibei_search": "Shibei 检索",
    "shibei_import": "Shibei 导入",
    "shibei_list_sources": "Shibei 索引",
    "memory": "更新记忆",
    "patch": "修改文件",
    "todo": "待办",
    "skills_list": "列出技能",
    "skill_view": "查看技能",
    "clarify": "澄清问题",
    "ask_user": "询问用户",
    "spawn_subagent": "委派子任务",
    "spawn_cli_agent": "委派 CLI Agent",
}


def progress_event_label(event: ProgressEvent) -> str:
    prefix = _subagent_prefix(event)
    if event.message.strip():
        return prefix + event.message.strip()
    if event.kind == "turn_started":
        return "开始处理"
    if event.kind == "turn_completed":
        return "本轮完成" if event.success else "本轮结束（待确认）"
    if event.kind == "pause_confirmation":
        return event.message.strip() or "等待确认"
    if event.kind == "iteration_started":
        return prefix + f"第 {event.iteration} 轮思考"
    if event.kind == "iteration_completed":
        return prefix + (event.message.strip() or "核实通过，准备输出")
    if event.kind == "tool_started":
        if event.tool_name == "spawn_subagent":
            return prefix + "正在委派子 Agent"
        if event.tool_name == "spawn_cli_agent":
            provider = event.archetype or "CLI"
            return prefix + f"正在运行 {provider} CLI Agent"
        if event.tool_name.startswith("browser_") or event.tool_name in {
            "web_search",
            "web_fetch",
        }:
            name = _tool_display_name(event.tool_name)
            return prefix + f"网络连接 · {name}"
        name = _tool_display_name(event.tool_name)
        return prefix + f"调用 {name}"
    if event.kind == "tool_finished":
        status = "完成" if event.success else "失败"
        if event.tool_name == "spawn_subagent":
            return prefix + f"子 Agent 委派{status}"
        if event.tool_name == "spawn_cli_agent":
            provider = event.archetype or "CLI"
            return prefix + f"{provider} CLI Agent {status}"
        if event.tool_name.startswith("browser_") or event.tool_name in {
            "web_search",
            "web_fetch",
        }:
            name = _tool_display_name(event.tool_name)
            return prefix + f"网络连接 · {name} {status}"
        name = _tool_display_name(event.tool_name)
        return prefix + f"{name} {status}"
    if event.kind == "subagent_started":
        archetype = event.archetype or "explore"
        return f"正在派生子 Agent ({archetype})"
    if event.kind == "subagent_paused":
        archetype = event.archetype or "explore"
        return f"子 Agent ({archetype}) 等待确认"
    if event.kind == "subagent_finished":
        prefix = f"[{event.archetype}] " if event.archetype else ""
        status = "完成" if event.success else "失败"
        detail = event.message[:80] if event.message else f"子任务{status}"
        return prefix + detail
    if event.kind == "cli_agent_started":
        provider = event.archetype or "CLI"
        return f"正在运行 {provider} CLI Agent"
    if event.kind == "cli_agent_finished":
        provider = event.archetype or "CLI"
        status = "完成" if event.success else "失败"
        detail = event.message[:80] if event.message else status
        return f"{provider} CLI Agent {status}: {detail}"
    if event.kind == "final_reply":
        return prefix + "整理回复"
    if event.kind == "stopped":
        return prefix + (event.message or "已停止")
    return prefix + event.kind


def _subagent_prefix(event: ProgressEvent) -> str:
    if event.archetype and event.sub_run_id:
        return f"[子Agent·{event.archetype}] "
    return ""


def _tool_display_name(name: str) -> str:
    if not name:
        return "工具"
    if name in _TOOL_LABELS:
        return _TOOL_LABELS[name]
    if name.startswith("mcp_"):
        parts = name.split("_", 2)
        if len(parts) == 3:
            return f"MCP {parts[1]}/{parts[2]}"
        return f"MCP {name[4:]}"
    return name


def progress_event_payload(event: ProgressEvent) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "kind": event.kind,
        "iteration": event.iteration,
        "tool_name": event.tool_name,
        "success": event.success,
        "label": progress_event_label(event),
    }
    if event.kind in {"reply_delta", "reply_start", "reply_end"} and event.message:
        payload["delta"] = event.message
    if event.detail.strip():
        payload["detail"] = event.detail.strip()
    if event.sub_run_id.strip():
        payload["sub_run_id"] = event.sub_run_id.strip()
    if event.archetype.strip():
        payload["archetype"] = event.archetype.strip()
    if event.goal.strip():
        payload["goal"] = event.goal.strip()
    if event.subagent_status.strip():
        payload["subagent_status"] = event.subagent_status.strip()
    if event.parent_sub_run_id.strip():
        payload["parent_sub_run_id"] = event.parent_sub_run_id.strip()
    if event.turn_id.strip():
        payload["turn_id"] = event.turn_id.strip()
    if event.thread_id.strip():
        payload["thread_id"] = event.thread_id.strip()
    if event.item_id.strip():
        payload["item_id"] = event.item_id.strip()
    if event.parent_turn_id.strip():
        payload["parent_turn_id"] = event.parent_turn_id.strip()
    return payload

