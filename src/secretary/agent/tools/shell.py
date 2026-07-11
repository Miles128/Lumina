"""Shell tool with read-only command detection."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolCall, ToolResult

_READ_ONLY_SHELL_CMDS = {
    "ls",
    "find",
    "mdfind",
    "mdls",
    "pwd",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "rg",
    "wc",
    "sort",
    "uniq",
    "cut",
    "stat",
    "du",
    "tree",
    "fd",
    "test",
    "nl",
    "xxd",
    "xattr",
    "which",
    "file",
    "realpath",
    "readlink",
    "basename",
    "dirname",
}


def _is_read_only_shell_command(command: str) -> bool:
    text = command.strip()
    if not text:
        return False
    if "&&" in text or "||" in text or ";" in text:
        return False
    if re.search(r">>\s*\S+", text):
        return False
    # 安全优先：基于正则的重定向检测会误判引号内的 >（如 grep 'a>b'），
    # 但误判方向是从"只读"变为"需确认"，不会把写操作误判为只读，因此可接受。
    # Allow redirection only to /dev/null
    for match in re.finditer(r"(?<!\d)>\s*(\S+)|\d>\s*(\S+)", text):
        target = (match.group(1) or match.group(2) or "").strip()
        if target != "/dev/null":
            return False
    if "<" in text and "</" not in text:
        return False

    segments = [seg.strip() for seg in text.split("\n") if seg.strip()]
    for segment in segments:
        parts = [p.strip() for p in segment.split("|") if p.strip()]
        if not parts:
            return False
        for part in parts:
            try:
                argv = shlex.split(part)
            except ValueError:
                return False
            if not argv:
                return False
            cmd = argv[0].lower()
            if cmd not in _READ_ONLY_SHELL_CMDS:
                return False
    return True


def _infer_shell_call_from_text(raw: str) -> ToolCall | None:
    command_inline = re.search(r"执行命令[:：]\s*`([^`]+)`", raw)
    if command_inline:
        command = command_inline.group(1).strip()
        if command:
            return ToolCall(name="shell", arguments={"command": command})

    cue_patterns = (
        "等 shell 结果",
        "等输出",
        "先搜",
        "先跑",
        "先执行",
        "先看",
    )
    if not any(cue in raw for cue in cue_patterns):
        return None
    match = re.search(r"```bash\s*\n(.*?)\n```", raw, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    command = match.group(1).strip()
    if not command:
        return None
    return ToolCall(name="shell", arguments={"command": command})


class ShellTool(Tool):
    name = "shell"
    description = "Execute a shell command. REQUIRES user confirmation before executing."
    needs_confirmation = True
    risk_level = "high"
    read_only = False
    _MAX_OUTPUT_CHARS = 12_000

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
            },
            "required": ["command"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        command = arguments.get("command", "")
        return f"⚡ 执行命令: `{command}`"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        command = str(arguments.get("command", "")).strip()
        timeout = min(int(arguments.get("timeout", 30) or 30), 120)
        if not command:
            return ToolResult.failure(
                "Error: empty command (model did not provide a command)",
                error_type="validation",
                retryable=False,
            )
        cwd = working_dir if working_dir.is_dir() else Path.home()
        env = os.environ.copy()

        # Prefer shell=False for simple commands (safer).  Fall back to
        # shell=True when the command contains pipes (which shlex.split
        # cannot handle) or when the executable is a shell builtin.
        needs_shell = "|" in command
        for attempt in range(2):
            try:
                if needs_shell:
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=str(cwd),
                        env=env,
                    )
                else:
                    argv = shlex.split(command)
                    result = subprocess.run(
                        argv,
                        shell=False,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=str(cwd),
                        env=env,
                    )
                break
            except OSError:
                # shell=False failed (e.g. shell builtin like "exit 3").
                # Retry once with shell=True.
                if attempt == 0 and not needs_shell:
                    needs_shell = True
                    continue
                return ToolResult.failure(
                    f"Error: failed to run command in {cwd}",
                    error_type="internal",
                    retryable=False,
                )
            except subprocess.TimeoutExpired:
                return ToolResult.failure(
                    f"Error: command timed out after {timeout}s",
                    error_type="timeout",
                    retryable=True,
                )
            except Exception as exc:
                return ToolResult.failure(
                    f"Error: {exc}",
                    error_type="internal",
                    retryable=False,
                )

        output = result.stdout or ""
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        output = output.strip() or "(no output)"
        if len(output) > self._MAX_OUTPUT_CHARS:
            output = output[: self._MAX_OUTPUT_CHARS] + "\n...[truncated]"
        return output
