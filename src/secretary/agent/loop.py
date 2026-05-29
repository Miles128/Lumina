"""Agent Loop: plan → act → observe → reflect cycle.

Read tools (file_read, list_dir) execute immediately.
Write tools (file_write, shell) require user confirmation via pending_actions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.memory.hermes_memory import HermesMemory
from secretary.services.file_auth import FileAuthService
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.stop_hooks import (
    LoopSnapshot,
    MaxIterationsStopHook,
    StopDecision,
    StopHook,
    ThirdPersonMetaReplyStopHook,
)

logger = logging.getLogger(__name__)

MAX_LOOP_STEPS = 12
MAX_TOOL_OUTPUT_CHARS = 4000
READABLE_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class StepResult:
    thought: str
    tool_call: ToolCall | None
    tool_output: str | None
    needs_confirmation: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LoopResult:
    reply: str
    steps: list[StepResult]
    used_tools: list[str]
    total_steps: int
    pending_confirmation: PendingConfirmation | None = None


@dataclass
class PendingConfirmation:
    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    description: str
    risk_level: str
    confirmation_kind: str = "action"


def _resolve_path(raw: str, working_dir: Path) -> Path:
    path = Path(raw or ".")
    if not path.is_absolute():
        path = working_dir / path
    return path.resolve()


class AgentLoop:
    def __init__(
        self,
        llm_config: LlmConfig,
        *,
        tools: list[Tool] | None = None,
        max_steps: int = MAX_LOOP_STEPS,
        working_dir: Path | None = None,
        file_auth: FileAuthService | None = None,
        stop_hooks: list[StopHook] | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> None:
        self._llm_config = llm_config
        self._tools = {t.name: t for t in (tools or _default_tools())}
        self._max_steps = max_steps
        self._working_dir = (working_dir or Path.home()).expanduser().resolve()
        if not self._working_dir.is_dir():
            self._working_dir = Path.home()
        self._file_auth = file_auth
        self._stop_hooks = stop_hooks or [
            MaxIterationsStopHook(max_steps),
            ThirdPersonMetaReplyStopHook(),
        ]
        self._progress_callback = progress_callback

    def run(self, messages: list[dict[str, str]], temperature: float = 0.7) -> LoopResult:
        steps: list[StepResult] = []
        used_tools: list[str] = []
        current_messages = list(messages)
        raw = ""
        thought = ""

        for step_idx in range(self._max_steps):
            iteration = step_idx + 1
            snapshot = LoopSnapshot(
                iteration=iteration,
                max_iterations=self._max_steps,
                latest_user_message=self._latest_user_message(current_messages),
            )
            decision = self._run_before_iteration_hooks(snapshot)
            if decision.should_stop:
                self._emit_progress(
                    ProgressEvent(
                        kind="stopped",
                        iteration=iteration,
                        message=decision.reason,
                        success=False,
                    )
                )
                return LoopResult(
                    reply=decision.reason or "已停止当前执行。",
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx,
                )

            self._emit_progress(
                ProgressEvent(kind="iteration_started", iteration=iteration)
            )
            tool_schemas = [t.schema() for t in self._tools.values()]
            payload = self._build_payload(current_messages, tool_schemas)

            on_delta = self._build_reply_delta_callback(iteration)
            raw = chat_completion(
                self._llm_config,
                payload,
                temperature=temperature,
                timeout=180.0,
                on_delta=on_delta,
            )
            if on_delta is not None:
                self._emit_progress(ProgressEvent(kind="reply_end", iteration=iteration))

            thought, tool_call = self._parse_response(raw)

            if tool_call is None:
                reply = self._sanitize_reply(thought, snapshot)
                self._emit_progress(
                    ProgressEvent(kind="final_reply", iteration=iteration, message=reply)
                )
                return LoopResult(
                    reply=reply,
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx + 1,
                )

            tool = self._tools.get(tool_call.name)
            if tool is None:
                tool_output = f"Error: unknown tool '{tool_call.name}'"
                step = StepResult(thought=thought, tool_call=tool_call, tool_output=tool_output)
                steps.append(step)
                current_messages.append({"role": "assistant", "content": raw})
                current_messages.append({
                    "role": "user",
                    "content": f"[Tool Result: {tool_call.name}]\n{tool_output}",
                })
                continue

            needs_confirm, confirmation_kind = self._requires_confirmation(
                tool,
                tool_call.arguments,
            )
            if needs_confirm:
                desc = tool.describe_action(tool_call.arguments, self._working_dir)
                risk = tool.risk_level
                action_id = f"act_{datetime.now(UTC).strftime('%H%M%S')}_{step_idx}"
                pending = PendingConfirmation(
                    action_id=action_id,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    description=desc,
                    risk_level=risk,
                    confirmation_kind=confirmation_kind,
                )
                step = StepResult(
                    thought=thought,
                    tool_call=tool_call,
                    tool_output=f"[Waiting for user confirmation] {desc}",
                    needs_confirmation=True,
                )
                steps.append(step)
                return LoopResult(
                    reply=f"我需要你的确认才能继续：\n\n{desc}\n\n是否允许？",
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx + 1,
                    pending_confirmation=pending,
                )

            try:
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_started",
                        iteration=iteration,
                        tool_name=tool_call.name,
                    )
                )
                tool_output = tool.execute(tool_call.arguments, self._working_dir)
                used_tools.append(tool_call.name)
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_finished",
                        iteration=iteration,
                        tool_name=tool_call.name,
                        success=True,
                    )
                )
            except Exception as exc:
                tool_output = f"Error executing {tool_call.name}: {exc}"
                logger.warning("Tool %s failed: %s", tool_call.name, exc)
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_finished",
                        iteration=iteration,
                        tool_name=tool_call.name,
                        success=False,
                        message=tool_output,
                    )
                )

            if len(tool_output) > MAX_TOOL_OUTPUT_CHARS:
                tool_output = tool_output[:MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"

            step = StepResult(thought=thought, tool_call=tool_call, tool_output=tool_output)
            steps.append(step)

            from secretary.agent.p0_tools import is_clarify_output

            if is_clarify_output(tool_output):
                if "\n" in tool_output:
                    clarify_reply = tool_output.split("\n", 1)[1].strip()
                else:
                    clarify_reply = thought
                reply = self._sanitize_reply(clarify_reply or thought, snapshot)
                self._emit_progress(
                    ProgressEvent(kind="final_reply", iteration=iteration, message=reply)
                )
                return LoopResult(
                    reply=reply,
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx + 1,
                )

            current_messages.append({"role": "assistant", "content": raw})
            current_messages.append({
                "role": "user",
                "content": f"[Tool Result: {tool_call.name}]\n{tool_output}",
            })

        snapshot = LoopSnapshot(
            iteration=self._max_steps,
            max_iterations=self._max_steps,
            latest_user_message=self._latest_user_message(current_messages),
        )
        reply = self._sanitize_reply(thought if steps else raw, snapshot)
        self._emit_progress(
            ProgressEvent(kind="final_reply", iteration=self._max_steps, message=reply)
        )
        return LoopResult(
            reply=reply,
            steps=steps,
            used_tools=used_tools,
            total_steps=self._max_steps,
        )

    def execute_confirmed(
        self,
        pending: PendingConfirmation,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> LoopResult:
        tool = self._tools.get(pending.tool_name)
        if tool is None:
            return LoopResult(reply="Error: tool no longer available", steps=[], used_tools=[], total_steps=0)

        try:
            tool_output = tool.execute(pending.arguments, self._working_dir)
        except Exception as exc:
            tool_output = f"Error: {exc}"

        if len(tool_output) > MAX_TOOL_OUTPUT_CHARS:
            tool_output = tool_output[:MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"

        current_messages = list(messages)
        current_messages.append({
            "role": "user",
            "content": f"[User confirmed: {pending.description}]\n[Tool Result: {pending.tool_name}]\n{tool_output}",
        })

        tool_schemas = [t.schema() for t in self._tools.values()]
        payload = self._build_payload(current_messages, tool_schemas)
        raw = chat_completion(self._llm_config, payload, temperature=temperature, timeout=180.0)
        thought, next_call = self._parse_response(raw)

        snapshot = LoopSnapshot(
            iteration=1,
            max_iterations=1,
            latest_user_message=self._latest_user_message(current_messages),
        )

        if next_call is None:
            reply = self._sanitize_reply(thought, snapshot)
            self._emit_progress(
                ProgressEvent(kind="final_reply", iteration=1, message=reply)
            )
            return LoopResult(reply=reply, steps=[], used_tools=[pending.tool_name], total_steps=1)

        # Model sometimes emits another tool-call style intermediate sentence
        # after a confirmed action. In confirm flow we must still return a
        # concrete result, so prefer the executed tool output.
        if tool_output.strip():
            reply = self._sanitize_reply(
                f"已执行并拿到结果：\n\n{tool_output}",
                snapshot,
            )
        else:
            reply = self._sanitize_reply(thought, snapshot)
        self._emit_progress(
            ProgressEvent(kind="final_reply", iteration=1, message=reply)
        )
        return LoopResult(
            reply=reply,
            steps=[StepResult(thought=thought, tool_call=next_call, tool_output=None)],
            used_tools=[pending.tool_name],
            total_steps=1,
            pending_confirmation=None,
        )

    def _requires_confirmation(
        self,
        tool: Tool,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        if tool.name == "file_write":
            path = _resolve_path(str(arguments.get("path", "")), self._working_dir)
            append = bool(arguments.get("append", False))
            if self._file_auth is None:
                kind = "write_modify" if path.exists() else "write_new"
                return True, kind
            kind = self._file_auth.write_confirmation_kind(path, append=append)
            if self._file_auth.needs_write_confirmation(path, append=append):
                return True, kind
            return False, ""

        if tool.name == "patch":
            path = _resolve_path(str(arguments.get("path", "")), self._working_dir)
            old_text = str(arguments.get("old_text", ""))
            if self._file_auth is None:
                kind = "write_modify" if path.exists() and old_text else "write_new"
                return True, kind
            if path.exists() and not old_text:
                return True, "write_modify"
            kind = self._file_auth.write_confirmation_kind(path, append=False)
            if self._file_auth.needs_write_confirmation(path, append=False):
                return True, kind
            return False, ""

        if tool.name == "file_delete":
            return True, "write_delete"

        if tool.name == "shell":
            command = str(arguments.get("command", "")).strip()
            if _is_read_only_shell_command(command):
                return False, ""
            return True, "shell"

        if tool.needs_confirmation:
            kind = "shell" if tool.name == "shell" else "action"
            return True, kind

        return False, ""

    def _run_before_iteration_hooks(self, snapshot: LoopSnapshot) -> StopDecision:
        for hook in self._stop_hooks:
            decision = hook.before_iteration(snapshot)
            if decision.should_stop:
                return decision
        return StopDecision(should_stop=False)

    def _sanitize_reply(self, reply: str, snapshot: LoopSnapshot) -> str:
        output = reply
        for hook in self._stop_hooks:
            output = hook.sanitize_reply(output, snapshot)
        return output

    def _latest_user_message(self, messages: list[dict[str, str]]) -> str:
        for item in reversed(messages):
            if item.get("role") == "user":
                return str(item.get("content", ""))
        return ""

    def _build_reply_delta_callback(self, iteration: int):
        if self._progress_callback is None:
            return None
        started = False

        def on_delta(delta: str) -> None:
            nonlocal started
            if not delta:
                return
            if not started:
                self._emit_progress(ProgressEvent(kind="reply_start", iteration=iteration))
                started = True
            self._emit_progress(
                ProgressEvent(kind="reply_delta", iteration=iteration, message=delta)
            )

        return on_delta

    def _emit_progress(self, event: ProgressEvent) -> None:
        if self._progress_callback is None:
            return
        try:
            self._progress_callback(event)
        except Exception as exc:  # pragma: no cover - defensive callback safety
            logger.debug("Progress callback failed: %s", exc)

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        tool_schemas: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        tools_desc = json.dumps(tool_schemas, ensure_ascii=False, indent=2)
        tool_names = ", ".join(self._tools.keys())
        instruction = (
            "You have access to the following tools. "
            "To use a tool, output a JSON block inside ```tool-call``` fences:\n"
            "```tool-call\n"
            '{"name": "<tool_name>", "arguments": {<args>}}\n'
            "```\n\n"
            f"Available tools: {tool_names}\n\n"
            f"Tool schemas:\n{tools_desc}\n\n"
            "Rules:\n"
            "- If you can answer directly without tools, do so.\n"
            "- Use only one tool per step.\n"
            "- After receiving tool results, decide if you need more steps or can answer.\n"
            "- When done, provide the final answer without any tool-call blocks.\n"
            "- Read tools (file_read, list_dir) execute immediately without confirmation.\n"
            "- New files can be created without repeated prompts after session write authorization.\n"
            "- Modifying or deleting files always needs user confirmation.\n"
            "- Write tools (file_write, patch, file_delete, shell) follow the authorization rules above.\n"
        )
        patched: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                patched.append({"role": "system", "content": msg["content"] + "\n\n" + instruction})
            else:
                patched.append(msg)
        if not any(m["role"] == "system" for m in messages):
            patched.insert(0, {"role": "system", "content": instruction})
        return patched

    def _parse_response(self, raw: str) -> tuple[str, ToolCall | None]:
        import re

        thought = raw
        tool_call = None

        pattern = r"```tool-call\s*\n(.*?)\n```"
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                name = data.get("name", "")
                arguments = data.get("arguments", {})
                if name and isinstance(arguments, dict):
                    tool_call = ToolCall(name=name, arguments=arguments)
                    thought = raw[: match.start()].strip()
                    if not thought:
                        thought = f"Calling tool: {name}"
            except json.JSONDecodeError:
                pass

        if tool_call is None:
            inferred = _infer_shell_call_from_text(raw)
            if inferred is not None:
                tool_call = inferred
                thought = "我先执行命令，再给你结果。"

        return thought, tool_call


class Tool:
    name: str = ""
    description: str = ""
    needs_confirmation: bool = False
    risk_level: str = "low"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._parameters(),
            "needs_confirmation": self.needs_confirmation,
        }

    def _parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        raise NotImplementedError

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"Execute {self.name}"


class ListDirTool(Tool):
    name = "list_dir"
    description = "List files and directories in a given path. Returns names, types, and sizes."
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list (default: current dir)"},
                "recursive": {"type": "boolean", "description": "List recursively (default: false, max depth 3)"},
                "pattern": {"type": "string", "description": "Glob pattern to filter (e.g. '*.py', '*.md')"},
            },
            "required": [],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        raw_path = arguments.get("path", ".")
        path = Path(raw_path)
        if not path.is_absolute():
            path = working_dir / path
        path = path.resolve()

        if not path.exists():
            return f"Error: path not found: {path}"
        if not path.is_dir():
            return f"Error: not a directory: {path}"

        try:
            if not os.access(path, os.R_OK):
                return f"Error: no read permission: {path}"
        except OSError as exc:
            return f"Error: {exc}"

        recursive = arguments.get("recursive", False)
        pattern = arguments.get("pattern", "*")

        lines: list[str] = []
        try:
            if recursive:
                max_depth = 3
                for root, dirs, files in os.walk(path):
                    rel = Path(root).relative_to(path)
                    depth = len(rel.parts)
                    if depth >= max_depth:
                        dirs.clear()
                        continue
                    for d in sorted(dirs):
                        dp = Path(root) / d
                        try:
                            if os.access(dp, os.R_OK):
                                lines.append(f"  {'  ' * depth}📁 {d}/")
                            else:
                                lines.append(f"  {'  ' * depth}🔒 {d}/")
                        except OSError:
                            lines.append(f"  {'  ' * depth}🔒 {d}/")
                    for f in sorted(files):
                        fp = Path(root) / f
                        try:
                            size = fp.stat().st_size
                            size_str = _human_size(size)
                        except OSError:
                            size_str = "?"
                        lines.append(f"  {'  ' * depth}📄 {f}  ({size_str})")
                    if len(lines) > 200:
                        lines.append(f"  ... (truncated, >200 entries)")
                        break
            else:
                entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                ext_counts: dict[str, int] = {}
                for entry in entries:
                    try:
                        if not os.access(entry, os.R_OK):
                            lines.append(f"🔒 {entry.name}")
                            continue
                    except OSError:
                        lines.append(f"🔒 {entry.name}")
                        continue
                    if entry.is_dir():
                        try:
                            count = sum(1 for _ in entry.iterdir())
                            lines.append(f"📁 {entry.name}/  ({count} items)")
                        except OSError:
                            lines.append(f"📁 {entry.name}/")
                    else:
                        try:
                            size = entry.stat().st_size
                            lines.append(f"📄 {entry.name}  ({_human_size(size)})")
                        except OSError:
                            lines.append(f"📄 {entry.name}")
                        suffix = entry.suffix.lower() or "(no_ext)"
                        ext_counts[suffix] = ext_counts.get(suffix, 0) + 1
                    if len(lines) > 100:
                        lines.append("... (truncated, >100 entries)")
                        break
                if ext_counts:
                    parts = [f"{ext}={count}" for ext, count in sorted(ext_counts.items())]
                    lines.insert(0, f"扩展名统计: {', '.join(parts)}")
        except PermissionError:
            return f"Error: permission denied: {path}"
        except Exception as exc:
            return f"Error listing directory: {exc}"

        header = f"📂 {path} ({len(lines)} entries)"
        return f"{header}\n" + "\n".join(lines)

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", ".")), working_dir)
        return f"📂 列出目录 `{path}`"


class FileReadTool(Tool):
    name = "file_read"
    description = "Read the contents of a file. No confirmation needed for reading."
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "Line offset (1-based)"},
                "limit": {"type": "integer", "description": "Max lines to read (default 200)"},
                "encoding": {"type": "string", "description": "File encoding (default utf-8)"},
            },
            "required": ["path"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = working_dir / path
        path = path.resolve()

        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"

        try:
            if not os.access(path, os.R_OK):
                return f"Error: no read permission: {path}"
        except OSError as exc:
            return f"Error: {exc}"

        try:
            file_size = path.stat().st_size
            if file_size > READABLE_MAX_BYTES:
                return f"Error: file too large ({_human_size(file_size)}), max {_human_size(READABLE_MAX_BYTES)}"

            encoding = arguments.get("encoding", "utf-8")
            content = path.read_text(encoding=encoding, errors="replace")
            lines = content.splitlines()
            offset = max(1, arguments.get("offset", 1)) - 1
            limit = arguments.get("limit", 200)
            selected = lines[offset : offset + limit]
            total_lines = len(lines)
            header = f"📄 {path} ({total_lines} lines, {_human_size(file_size)})"
            body = "\n".join(f"{i + offset + 1}: {line}" for i, line in enumerate(selected))
            if offset + limit < total_lines:
                body += f"\n... ({total_lines - offset - limit} more lines)"
            return f"{header}\n{body}"
        except Exception as exc:
            return f"Error reading file: {exc}"

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        return f"📖 读取文件 `{path}`"


class FileWriteTool(Tool):
    name = "file_write"
    description = "Write content to a file. REQUIRES user confirmation before executing."
    needs_confirmation = True
    risk_level = "medium"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default false)"},
            },
            "required": ["path", "content"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = working_dir / path
        content = arguments.get("content", "")
        append = arguments.get("append", False)
        action = "追加" if append else "写入"
        exists = path.exists()
        size_info = f" ({len(content)} 字符)"
        if exists:
            return f"📝 {action}文件 `{path}`（文件已存在，将被{'追加' if append else '覆盖'}）{size_info}"
        return f"📝 {action}新文件 `{path}`{size_info}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = Path(arguments.get("path", ""))
        if not path.is_absolute():
            path = working_dir / path
        content = arguments.get("content", "")
        append = arguments.get("append", False)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if append:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                path.write_text(content, encoding="utf-8")
            return f"OK: wrote {len(content)} chars to {path}"
        except Exception as exc:
            return f"Error writing file: {exc}"


class FileDeleteTool(Tool):
    name = "file_delete"
    description = "Delete a file. Always requires user confirmation before executing."
    needs_confirmation = True
    risk_level = "high"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
            },
            "required": ["path"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        return f"🗑️ 删除文件 `{path}`"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        if not path.exists():
            return f"Error: file not found: {path}"
        if not path.is_file():
            return f"Error: not a file: {path}"
        try:
            path.unlink()
            return f"OK: deleted {path}"
        except Exception as exc:
            return f"Error deleting file: {exc}"


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


class SearchMemoryTool(Tool):
    name = "search_memory"
    description = "Search local memory store for relevant information."
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        }

    def __init__(self, store: Any) -> None:
        self._store = store

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        query = arguments.get("query", "")
        limit = arguments.get("limit", 5)
        chunks = self._store.search(query, limit=limit)
        if not chunks:
            return "No results found."
        lines = []
        for i, chunk in enumerate(chunks, 1):
            snippet = chunk.content[:300].replace("\n", " ")
            lines.append(f"{i}. [{chunk.source.value}] {chunk.title}\n   {snippet}")
        return "\n".join(lines)


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch and extract text content from a URL."
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)"},
            },
            "required": ["url"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        url = arguments.get("url", "")
        max_chars = arguments.get("max_chars", 3000)
        if not url.startswith(("http://", "https://")):
            return "Error: only http/https URLs are supported"
        try:
            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "Lumina/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            import re

            body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL)
            body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL)
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()
            if len(body) > max_chars:
                body = body[:max_chars] + "..."
            return body or "(empty response)"
        except Exception as exc:
            return f"Error fetching URL: {exc}"


class MemoryTool(Tool):
    name = "memory"
    description = (
        "Manage durable cross-session memory. "
        "target=memory edits MEMORY.md (environment/project facts); "
        "target=user edits USER.md (preferences/profile). "
        "Actions: add, replace (requires old_text), remove (requires old_text)."
    )
    needs_confirmation = False
    risk_level = "low"

    def __init__(self, hermes: HermesMemory) -> None:
        self._hermes = hermes

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove"],
                    "description": "Memory operation",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "memory=MEMORY.md, user=USER.md",
                },
                "text": {"type": "string", "description": "Text to add or replacement text"},
                "old_text": {
                    "type": "string",
                    "description": "Substring to replace or remove (required for replace/remove)",
                },
            },
            "required": ["action", "target"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        try:
            return self._hermes.mutate_memory(
                str(arguments.get("action", "")),
                str(arguments.get("target", "")),
                text=str(arguments.get("text", "")),
                old_text=str(arguments.get("old_text", "")),
            )
        except ValueError as exc:
            return f"Error: {exc}"


class SessionSearchTool(Tool):
    name = "session_search"
    description = "Search past conversation sessions for relevant messages."
    needs_confirmation = False
    risk_level = "low"

    def __init__(self, hermes: HermesMemory) -> None:
        self._hermes = hermes

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 8)"},
            },
            "required": ["query"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "Error: empty query"
        limit = int(arguments.get("limit", 8))
        results = self._hermes.search_sessions(query, limit=limit)
        if not results:
            return "No matching session messages found."
        lines: list[str] = []
        for index, item in enumerate(results, start=1):
            role = item["role"]
            snippet = item["content"].replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "…"
            lines.append(
                f"{index}. [{item['session_id']}] {role} @ {item['timestamp']}\n   {snippet}"
            )
        return "\n".join(lines)


def _default_tools() -> list[Tool]:
    from secretary.agent.web_search import WebSearchTool

    return [
        ListDirTool(),
        FileReadTool(),
        FileWriteTool(),
        FileDeleteTool(),
        ShellTool(),
        WebFetchTool(),
        WebSearchTool(),
    ]


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"


_READ_ONLY_SHELL_CMDS = {
    "ls",
    "find",
    "pwd",
    "cat",
    "head",
    "tail",
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
    import re

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
