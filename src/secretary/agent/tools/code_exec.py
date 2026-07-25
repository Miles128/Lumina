"""Sandboxed Python snippet execution (workspace read-only, temp cwd write, confirm)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from secretary.agent.text_utils import truncate_chars
from secretary.agent.tools.base import Tool

_MAX_OUTPUT_CHARS = 12_000
_MAX_CODE_CHARS = 40_000
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 60

# Drop credentials / proxy hints from the child environment.
_STRIP_ENV_PREFIXES = (
    "AWS_",
    "AZURE_",
    "GOOGLE_",
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "LLM_",
    "SECRETARY_",
    "DEEPSEEK_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)

_SANDBOX_BOOTSTRAP = '''\
import builtins
import os
import shutil
import socket
import sys

_SANDBOX_ROOT = os.path.realpath(os.getcwd())
_WORKSPACE_ROOT = os.path.realpath(os.environ.get("LUMINA_WORKSPACE", _SANDBOX_ROOT))
_ORIG_OPEN = builtins.open
_ORIG_SOCKET = socket.socket
_ORIG_REMOVE = os.remove
_ORIG_UNLINK = getattr(os, "unlink", os.remove)
_ORIG_RENAME = os.rename
_ORIG_REPLACE = getattr(os, "replace", os.rename)
_ORIG_RMDIR = os.rmdir
_ORIG_SHUTIL_RMTree = shutil.rmtree
_ORIG_SHUTIL_MOVE = shutil.move
_ORIG_SHUTIL_COPY = shutil.copy
_ORIG_SHUTIL_COPY2 = shutil.copy2
_ORIG_SHUTIL_COPYTREE = shutil.copytree


def _under(root, path):
    return path == root or path.startswith(root + os.sep)


def _is_write_mode(mode):
    return isinstance(mode, str) and any(ch in mode for ch in "wax+")


def _as_path(file):
    if isinstance(file, int):
        return None
    try:
        path = os.fspath(file)
    except TypeError:
        return None
    if not isinstance(path, str):
        return None
    return path


def _resolve_under(root, path):
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))


def _guarded_open(file, mode="r", *args, **kwargs):
    path = _as_path(file)
    if path is None:
        return _ORIG_OPEN(file, mode, *args, **kwargs)
    write = _is_write_mode(mode)
    if write:
        resolved = _resolve_under(_SANDBOX_ROOT, path)
        if not _under(_SANDBOX_ROOT, resolved):
            raise PermissionError(f"sandbox: cannot write outside sandbox cwd: {resolved}")
        return _ORIG_OPEN(resolved, mode, *args, **kwargs)
    # Read: relative prefers sandbox hit, else workspace; absolute must be under either root.
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
        if not (_under(_SANDBOX_ROOT, resolved) or _under(_WORKSPACE_ROOT, resolved)):
            raise PermissionError(f"sandbox: cannot open outside workspace/sandbox: {resolved}")
        return _ORIG_OPEN(file, mode, *args, **kwargs)
    sand = _resolve_under(_SANDBOX_ROOT, path)
    ws = _resolve_under(_WORKSPACE_ROOT, path)
    if _under(_SANDBOX_ROOT, sand) and os.path.exists(sand):
        return _ORIG_OPEN(sand, mode, *args, **kwargs)
    if _under(_WORKSPACE_ROOT, ws) and os.path.exists(ws):
        return _ORIG_OPEN(ws, mode, *args, **kwargs)
    if not _under(_SANDBOX_ROOT, sand):
        raise PermissionError(f"sandbox: cannot open outside workspace/sandbox: {sand}")
    return _ORIG_OPEN(sand, mode, *args, **kwargs)


def _assert_sandbox_write(path, op):
    resolved = os.path.realpath(path if os.path.isabs(path) else os.path.join(_SANDBOX_ROOT, path))
    if not _under(_SANDBOX_ROOT, resolved):
        raise PermissionError(f"sandbox: cannot {op} outside sandbox cwd: {resolved}")
    return resolved


def _guarded_remove(path, *args, **kwargs):
    _assert_sandbox_write(path, "remove")
    return _ORIG_REMOVE(path, *args, **kwargs)


def _guarded_unlink(path, *args, **kwargs):
    _assert_sandbox_write(path, "unlink")
    return _ORIG_UNLINK(path, *args, **kwargs)


def _guarded_rename(src, dst, *args, **kwargs):
    _assert_sandbox_write(src, "rename")
    _assert_sandbox_write(dst, "rename")
    return _ORIG_RENAME(src, dst, *args, **kwargs)


def _guarded_replace(src, dst, *args, **kwargs):
    _assert_sandbox_write(src, "replace")
    _assert_sandbox_write(dst, "replace")
    return _ORIG_REPLACE(src, dst, *args, **kwargs)


def _guarded_rmdir(path, *args, **kwargs):
    _assert_sandbox_write(path, "rmdir")
    return _ORIG_RMDIR(path, *args, **kwargs)


def _guarded_rmtree(path, *args, **kwargs):
    _assert_sandbox_write(path, "rmtree")
    return _ORIG_SHUTIL_RMTree(path, *args, **kwargs)


def _guarded_move(src, dst, *args, **kwargs):
    _assert_sandbox_write(src, "move")
    _assert_sandbox_write(dst, "move")
    return _ORIG_SHUTIL_MOVE(src, dst, *args, **kwargs)


def _guarded_copy(src, dst, *args, **kwargs):
    # Allow reading workspace via copy into sandbox only.
    src_resolved = os.path.realpath(src if os.path.isabs(src) else os.path.join(_SANDBOX_ROOT, src))
    if not (_under(_SANDBOX_ROOT, src_resolved) or _under(_WORKSPACE_ROOT, src_resolved)):
        raise PermissionError(f"sandbox: cannot copy from outside workspace/sandbox: {src_resolved}")
    _assert_sandbox_write(dst, "copy")
    return _ORIG_SHUTIL_COPY(src, dst, *args, **kwargs)


def _guarded_copy2(src, dst, *args, **kwargs):
    src_resolved = os.path.realpath(src if os.path.isabs(src) else os.path.join(_SANDBOX_ROOT, src))
    if not (_under(_SANDBOX_ROOT, src_resolved) or _under(_WORKSPACE_ROOT, src_resolved)):
        raise PermissionError(f"sandbox: cannot copy from outside workspace/sandbox: {src_resolved}")
    _assert_sandbox_write(dst, "copy")
    return _ORIG_SHUTIL_COPY2(src, dst, *args, **kwargs)


def _guarded_copytree(src, dst, *args, **kwargs):
    src_resolved = os.path.realpath(src if os.path.isabs(src) else os.path.join(_SANDBOX_ROOT, src))
    if not (_under(_SANDBOX_ROOT, src_resolved) or _under(_WORKSPACE_ROOT, src_resolved)):
        raise PermissionError(f"sandbox: cannot copytree from outside workspace/sandbox: {src_resolved}")
    _assert_sandbox_write(dst, "copytree")
    return _ORIG_SHUTIL_COPYTREE(src, dst, *args, **kwargs)


class _GuardedSocket(_ORIG_SOCKET):
    def __init__(self, *args, **kwargs):
        raise PermissionError("sandbox: network disabled")


builtins.open = _guarded_open
socket.socket = _GuardedSocket
os.remove = _guarded_remove
os.unlink = _guarded_unlink
os.rename = _guarded_rename
os.replace = _guarded_replace
os.rmdir = _guarded_rmdir
shutil.rmtree = _guarded_rmtree
shutil.move = _guarded_move
shutil.copy = _guarded_copy
shutil.copy2 = _guarded_copy2
shutil.copytree = _guarded_copytree
'''


def _sandbox_env(tmp_path: Path, workspace: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(key.startswith(prefix) or key == prefix for prefix in _STRIP_ENV_PREFIXES)
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["HOME"] = str(tmp_path)
    env["TMPDIR"] = str(tmp_path)
    env["TEMP"] = str(tmp_path)
    env["TMP"] = str(tmp_path)
    env["LUMINA_WORKSPACE"] = str(workspace.resolve())
    # Prefer our sitecustomize / bootstrap over user site.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


class CodeExecTool(Tool):
    name = "code_exec"
    description = (
        "Run a short Python snippet in an isolated temporary working directory. "
        "May READ files under the current workspace (absolute path or relative name "
        "resolved via workspace if not in the sandbox). Writes are allowed ONLY inside "
        "the temp sandbox — never write the workspace from here; use write/edit "
        "to persist. Network is blocked. REQUIRES user confirmation (once per session "
        "after approval). Prefer read_document for Excel/PDF/Word; use this for "
        "computation, parsing, transforms. On non-zero exit, fix the code and re-run."
    )
    needs_confirmation = True
    risk_level = "high"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute (written to a temp .py file)",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds (default {_DEFAULT_TIMEOUT}, max {_MAX_TIMEOUT})",
                },
            },
            "required": ["code"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        code = str(arguments.get("code", "")).strip()
        preview = code.splitlines()[0][:80] if code else ""
        return f"🐍 运行 Python: `{preview}`"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        code = str(arguments.get("code", ""))
        if not code.strip():
            return "Error: empty code"
        if len(code) > _MAX_CODE_CHARS:
            return f"Error: code exceeds {_MAX_CODE_CHARS} characters"

        timeout = min(int(arguments.get("timeout", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
        timeout = max(1, timeout)
        workspace = working_dir.resolve()

        with tempfile.TemporaryDirectory(prefix="lumina-code-exec-") as tmp:
            tmp_path = Path(tmp)
            bootstrap = tmp_path / "_run.py"
            bootstrap.write_text(
                _SANDBOX_BOOTSTRAP
                + "\nimport runpy\n"
                + "runpy.run_path('snippet.py', run_name='__main__')\n",
                encoding="utf-8",
            )
            script = tmp_path / "snippet.py"
            script.write_text(code, encoding="utf-8")
            try:
                result = subprocess.run(
                    # -I: ignore PYTHON* env and user site; script dir still needed via cwd exec.
                    # Use -E -s so the runner file's directory stays on sys.path for runpy.
                    [sys.executable, "-E", "-s", str(bootstrap)],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(tmp_path),
                    env=_sandbox_env(tmp_path, workspace),
                )
            except subprocess.TimeoutExpired:
                return f"Error: code timed out after {timeout}s"
            except Exception as exc:
                return f"Error: {exc}"

        output = result.stdout or ""
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        output = output.strip() or "(no output)"
        return truncate_chars(output, _MAX_OUTPUT_CHARS)
