"""Shell tool with read-only command detection."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolCall

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
    "awk",
    "sed",
    "stat",
    "du",
    "tree",
    "fd",
    "echo",
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
            if cmd == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in argv[1:]):
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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        command = str(arguments.get("command", "")).strip()
        timeout = min(int(arguments.get("timeout", 30) or 30), 120)
        if not command:
            return "Error: empty command"
        cwd = working_dir if working_dir.is_dir() else Path.home()
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd),
                env=os.environ.copy(),
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
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {timeout}s"
        except OSError as exc:
            return f"Error: failed to run command in {cwd}: {exc}"
        except Exception as exc:
            return f"Error: {exc}"
