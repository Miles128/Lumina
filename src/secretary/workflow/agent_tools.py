"""Minimal tool sets for workflow AgentLoop nodes (no spawn_subagent)."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.p0_tools import EditTool, GlobFilesTool, SearchFilesTool
from secretary.agent.tools.base import Tool
from secretary.agent.tools.code_exec import CodeExecTool
from secretary.agent.tools.fs import ListDirTool, MoveTool, ReadTool, WriteTool
from secretary.agent.tools.shell import ShellTool
from secretary.agent.tools.web import WebFetchTool
from secretary.agent.web_search import WebSearchTool


def tools_for_workflow_profile(profile: str, **_: object) -> list[Tool]:
    """Ask = read-only (+ web); build = ask + write/shell/code_exec. Never spawn."""
    normalized = (profile or "ask").strip().lower()
    read_tools: list[Tool] = [
        ListDirTool(),
        ReadTool(),
        SearchFilesTool(),
        GlobFilesTool(),
        WebSearchTool(),
        WebFetchTool(),
    ]
    if normalized in {"build", "auto"}:
        return [
            *read_tools,
            WriteTool(),
            EditTool(),
            MoveTool(),
            ShellTool(),
            CodeExecTool(),
        ]
    return read_tools


def resolve_working_dir(raw: str | None, fallback: Path | None) -> Path | None:
    if raw and str(raw).strip():
        path = Path(str(raw).strip()).expanduser()
        if path.is_dir():
            return path.resolve()
    if fallback is not None and fallback.is_dir():
        return fallback.resolve()
    return fallback
