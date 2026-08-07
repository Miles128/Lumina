"""Confirmation policy for write/shell/MCP tools (read-only tools never pause)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secretary.agent.fs_jail import get_full_fs_access, is_writable_path, shell_escapes_jail
from secretary.agent.harness_config import ConfirmRequireConfig
from secretary.agent.tools.base import Tool, _resolve_path
from secretary.agent.tools.shell import _is_read_only_shell_command
from secretary.services.file_auth import FileAuthService


def _is_thread_sandbox(working_dir: Path) -> bool:
    """True when the working dir is a per-thread sandbox (isolated, disposable)."""
    parts = Path(working_dir).expanduser().resolve().parts
    return ".lumina" in parts and "sandbox" in parts


def _kind_require_key(kind: str) -> str:
    """Map confirmation kind → ConfirmRequireConfig field name."""
    if kind == "write_move":
        return "write_modify"
    if kind in {"write_new", "write_modify", "write_delete", "shell", "action"}:
        return kind
    return "action"


def kind_requires_confirm(
    kind: str,
    require_confirm: ConfirmRequireConfig | None,
) -> bool:
    """Return False when harness has disabled confirmation for this kind."""
    if require_confirm is None:
        return True
    key = _kind_require_key(kind)
    return bool(getattr(require_confirm, key, True))


def tool_requires_confirmation(
    tool: Tool,
    arguments: dict[str, Any],
    *,
    working_dir: Path,
    file_auth: FileAuthService | None,
    require_confirm: ConfirmRequireConfig | None = None,
    full_fs_access: bool | None = None,
) -> tuple[bool, str]:
    """Return (needs_confirmation, kind) for a tool invocation."""
    if tool.read_only:
        return False, ""

    if full_fs_access is None:
        full_fs_access = get_full_fs_access()

    # Hard sandbox (default): skip confirms for in-jail writes + code_exec.
    # Opens「完全权限」→ fall through to permission_mode / require_confirm.
    if not full_fs_access:
        from secretary.agent.tools.fs import EDIT_TOOL_NAMES, WRITE_TOOL_NAMES

        if tool.name == "code_exec":
            return False, ""
        if tool.name in WRITE_TOOL_NAMES or tool.name in EDIT_TOOL_NAMES:
            path = _resolve_path(
                str(arguments.get("path") or arguments.get("file_path") or ""),
                working_dir,
            )
            if is_writable_path(path, working_dir, full_fs_access=False):
                return False, ""

    # MCP tools: trust flags set at construction from the bare remote name.
    # Never re-run name heuristics on `mcp_{server}_{tool}` — server tokens
    # like "search" would false-negative write tools.
    if tool.name.startswith("mcp_"):
        if tool.needs_confirmation:
            kind = "action"
            if not kind_requires_confirm(kind, require_confirm):
                return False, ""
            return True, kind
        return False, ""

    from secretary.agent.tools.fs import EDIT_TOOL_NAMES, MOVE_TOOL_NAMES, WRITE_TOOL_NAMES

    if tool.name in WRITE_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        append = bool(arguments.get("append", False))
        if file_auth is None:
            kind = "write_modify" if path.exists() else "write_new"
        else:
            kind = file_auth.write_confirmation_kind(path, append=append)
            if not file_auth.needs_write_confirmation(path, append=append):
                return False, ""
        if not kind_requires_confirm(kind, require_confirm):
            return False, ""
        return True, kind

    if tool.name in EDIT_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        if file_auth is None:
            kind = "write_modify" if path.exists() else "write_new"
        else:
            kind = file_auth.write_confirmation_kind(path, append=False)
            if not file_auth.needs_write_confirmation(path, append=False):
                return False, ""
        if not kind_requires_confirm(kind, require_confirm):
            return False, ""
        return True, kind

    if tool.name in MOVE_TOOL_NAMES:
        kind = "write_move"
        if not kind_requires_confirm(kind, require_confirm):
            return False, ""
        return True, kind

    if tool.name == "file_delete":
        kind = "write_delete"
        if not kind_requires_confirm(kind, require_confirm):
            return False, ""
        return True, kind

    if tool.name == "shell":
        command = str(arguments.get("command", "")).strip()
        if not command:
            return False, ""  # empty → skip; execute returns error
        if _is_read_only_shell_command(command):
            return False, ""
        # Thread-sandbox shells are free: the cwd is an isolated directory, so
        # as long as every absolute path stays inside it (fs_jail check) the
        # command cannot touch the outside world. Real workspaces stay gated.
        if _is_thread_sandbox(working_dir) and shell_escapes_jail(command, working_dir) is None:
            return False, ""
        kind = "shell"
        if not kind_requires_confirm(kind, require_confirm):
            return False, ""
        return True, kind

    if tool.name == "code_exec":
        # code_exec is a soft sandbox by construction (read-only workspace,
        # temp cwd, no network) — it cannot damage anything, so it never needs
        # confirmation regardless of permission mode.
        return False, ""

    if tool.needs_confirmation:
        kind = "shell" if tool.name == "shell" else "action"
        if not kind_requires_confirm(kind, require_confirm):
            return False, ""
        return True, kind

    return False, ""
