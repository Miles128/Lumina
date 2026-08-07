"""Confirmation policy for write/shell/MCP tools (read-only tools never pause)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secretary.agent.fs_jail import get_full_fs_access, is_writable_path, shell_escapes_jail
from secretary.agent.harness_config import ConfirmRequireConfig, infer_permission_mode
from secretary.agent.tools.base import Tool, _resolve_path
from secretary.agent.tools.shell import _is_read_only_shell_command
from secretary.services.file_auth import FileAuthService

_WRITE_SHELL_CMDS = frozenset(
    {"echo", "touch", "mkdir", "cp", "mv", "rm", "rmdir", "tee", "truncate", "install", "ln", "chmod", "chown"}
)


def _shell_runs_in_cwd_python(command: str, working_dir: Path) -> bool:
    """True when the command runs a python script that resolves inside the cwd.

    Supports chained commands (a && b / a; b) as long as the FIRST segment is
    the python run — the model's script-execution step is what matters.
    """
    import shlex as _shlex

    if shell_escapes_jail(command, working_dir, full_fs_access=False) is not None:
        return False
    first_seg = re.split(r"&&|;", command)[0].strip()
    try:
        argv = _shlex.split(first_seg)
    except ValueError:
        return False
    if not argv:
        return False
    if argv[0].lower() not in _PYTHON_CMDS:
        return False
    if len(argv) < 2 or argv[1].startswith("-"):
        return False
    script = _resolve_path(argv[1], working_dir)
    return is_writable_path(script, working_dir, full_fs_access=False)


_PYTHON_CMDS = frozenset({"python", "python3", "pypy3"})


def _shell_writes_inside_cwd(command: str, working_dir: Path) -> bool:
    """True when a shell command is a file operation that stays in the cwd."""
    # Always enforce the jail here: full access relaxes path scope for the
    # write tools, but this auto-mode exemption must still see real escapes.
    if shell_escapes_jail(command, working_dir, full_fs_access=False) is not None:
        return False
    if ">" in command or ">>" in command:
        return True
    try:
        import shlex

        argv = shlex.split(command.split("|")[0].strip())
    except ValueError:
        return False
    if not argv:
        return False
    return argv[0].lower() in _WRITE_SHELL_CMDS


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

    # Writes inside the active working_dir never confirm — whether that is the
    # per-thread sandbox (isolated) or a user-selected workspace (they asked for
    # files to land there). Escaping the working_dir still confirms; file
    # deletes stay gated.
    if tool.name in WRITE_TOOL_NAMES or tool.name in EDIT_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        if is_writable_path(path, working_dir, full_fs_access=False):
            return False, ""
    elif tool.name in MOVE_TOOL_NAMES:
        dst = _resolve_path(str(arguments.get("to_path", "")), working_dir)
        if is_writable_path(dst, working_dir, full_fs_access=False):
            return False, ""

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
        # Executing a Python script that lives inside the working dir (written
        # by the write tool, outputs kept in-cwd) is free — this is the
        # write→run→produce loop the product guarantees, regardless of mode.
        if _shell_runs_in_cwd_python(command, working_dir):
            return False, ""
        # auto mode: file-operation shells inside the working dir (touch/mkdir/
        # cp/mv/rm/echo>…, no jail escape) are free — same spirit as the
        # in-cwd write exemption; arbitrary commands still confirm.
        if (
            require_confirm is not None
            and infer_permission_mode(require_confirm) == "auto"
            and _shell_writes_inside_cwd(command, working_dir)
        ):
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
