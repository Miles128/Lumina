"""Confirmation policy for write/shell/MCP tools (read-only tools never pause)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, _resolve_path
from secretary.agent.tools.shell import _is_read_only_shell_command
from secretary.services.file_auth import FileAuthService


def tool_requires_confirmation(
    tool: Tool,
    arguments: dict[str, Any],
    *,
    working_dir: Path,
    file_auth: FileAuthService | None,
) -> tuple[bool, str]:
    """Return (needs_confirmation, kind) for a tool invocation."""
    if tool.read_only:
        return False, ""
    # MCP tools: trust flags set at construction from the bare remote name.
    # Never re-run name heuristics on `mcp_{server}_{tool}` — server tokens
    # like "search" would false-negative write tools.
    if tool.name.startswith("mcp_"):
        if tool.needs_confirmation:
            return True, "action"
        return False, ""

    from secretary.agent.tools.fs import EDIT_TOOL_NAMES, MOVE_TOOL_NAMES, WRITE_TOOL_NAMES

    if tool.name in WRITE_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        append = bool(arguments.get("append", False))
        if file_auth is None:
            kind = "write_modify" if path.exists() else "write_new"
            return True, kind
        kind = file_auth.write_confirmation_kind(path, append=append)
        if file_auth.needs_write_confirmation(path, append=append):
            return True, kind
        return False, ""

    if tool.name in EDIT_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        if file_auth is None:
            return True, "write_modify" if path.exists() else "write_new"
        kind = file_auth.write_confirmation_kind(path, append=False)
        if file_auth.needs_write_confirmation(path, append=False):
            return True, kind
        return False, ""

    if tool.name in MOVE_TOOL_NAMES:
        return True, "write_move"

    if tool.name == "file_delete":
        return True, "write_delete"

    if tool.name == "shell":
        command = str(arguments.get("command", "")).strip()
        if not command:
            return False, ""  # empty → skip; execute returns error
        if _is_read_only_shell_command(command):
            return False, ""
        return True, "shell"

    if tool.name == "code_exec":
        if file_auth is not None and file_auth.has_session_code_exec():
            return False, ""
        return True, "action"

    if tool.needs_confirmation:
        kind = "shell" if tool.name == "shell" else "action"
        return True, kind

    return False, ""
