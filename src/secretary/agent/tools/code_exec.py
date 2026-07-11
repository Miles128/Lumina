"""Sandboxed Python snippet execution (temp cwd, timeout, confirm required)."""

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
import socket
import sys

_ALLOWED_ROOT = os.path.realpath(os.getcwd())
_ORIG_OPEN = builtins.open
_ORIG_SOCKET = socket.socket


def _resolve_path(file):
    if isinstance(file, (int,)):
        return None
    try:
        path = os.fspath(file)
    except TypeError:
        return None
    if not isinstance(path, str):
        return None
    # Relative paths resolve under cwd; absolute must stay inside.
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(_ALLOWED_ROOT, path))


def _guarded_open(file, *args, **kwargs):
    resolved = _resolve_path(file)
    if resolved is not None:
        allowed = resolved == _ALLOWED_ROOT or resolved.startswith(_ALLOWED_ROOT + os.sep)
        if not allowed:
            raise PermissionError(f"sandbox: cannot open outside cwd: {resolved}")
    return _ORIG_OPEN(file, *args, **kwargs)


class _GuardedSocket(_ORIG_SOCKET):
    def __init__(self, *args, **kwargs):
        raise PermissionError("sandbox: network disabled")


builtins.open = _guarded_open
socket.socket = _GuardedSocket
'''


def _sandbox_env(tmp_path: Path) -> dict[str, str]:
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
    # Prefer our sitecustomize / bootstrap over user site.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


class CodeExecTool(Tool):
    name = "code_exec"
    description = (
        "Run a short Python snippet in an isolated temporary working directory. "
        "Stdout/stderr are captured. Network and filesystem access outside the "
        "temp dir are blocked. REQUIRES user confirmation. "
        "Prefer read_document for Excel/PDF/Word; use this for computation or parsing."
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
                    env=_sandbox_env(tmp_path),
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
