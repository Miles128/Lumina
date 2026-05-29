"""Structured progress events for agent loop instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProgressKind = Literal[
    "iteration_started",
    "tool_started",
    "tool_finished",
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


_TOOL_LABELS: dict[str, str] = {
    "list_dir": "浏览目录",
    "file_read": "读取文件",
    "file_write": "写入文件",
    "file_delete": "删除文件",
    "search_files": "搜索文件",
    "shell": "执行命令",
    "search_memory": "搜索记忆",
    "session_search": "搜索会话",
    "web_search": "联网搜索",
    "web_fetch": "抓取网页",
    "memory": "更新记忆",
    "patch": "修改文件",
    "todo": "待办",
    "skills_list": "列出技能",
    "skill_view": "查看技能",
    "clarify": "澄清问题",
}


def progress_event_label(event: ProgressEvent) -> str:
    if event.message.strip():
        return event.message.strip()
    if event.kind == "iteration_started":
        return f"第 {event.iteration} 轮思考"
    if event.kind == "tool_started":
        return f"调用 {_tool_display_name(event.tool_name)}"
    if event.kind == "tool_finished":
        status = "完成" if event.success else "失败"
        return f"{_tool_display_name(event.tool_name)} {status}"
    if event.kind == "final_reply":
        return "整理回复"
    if event.kind == "stopped":
        return event.message or "已停止"
    return event.kind


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
        "kind": event.kind,
        "iteration": event.iteration,
        "tool_name": event.tool_name,
        "success": event.success,
        "label": progress_event_label(event),
    }
    if event.kind in {"reply_delta", "reply_start", "reply_end"} and event.message:
        payload["delta"] = event.message
    return payload

