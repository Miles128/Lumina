"""Agent Loop: plan → act → observe → reflect cycle.

Read tools (file_read, list_dir) execute immediately.
Write tools (file_write, shell) require user confirmation via pending_actions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from secretary.agent.grounding import (
    GROUNDING_RETRY_USER,
    collect_command_evidence,
    collect_read_evidence,
    enforce_grounded_reply,
    format_verify_retry,
    has_read_grounding,
    infer_list_dir_target,
    is_filesystem_question,
    reply_defers_filesystem_work,
    requires_forced_read_tool,
    resolve_turn_user_message,
    sanitize_filesystem_reply,
    should_retry_for_grounding,
    should_retry_for_verification,
    verify_reply_against_evidence,
)
from secretary.agent.llm_client import (
    ChatCompletionResult,
    chat_completion,
    chat_completion_with_tools,
    schemas_to_openai_tools,
)
from secretary.agent.llm_config import LlmConfig
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.stop_hooks import (
    LoopSnapshot,
    MaxIterationsStopHook,
    StopDecision,
    StopHook,
    ThirdPersonMetaReplyStopHook,
)
from secretary.agent.tools.base import Tool, ToolCall, _resolve_path
from secretary.agent.tools.fs import (
    FileDeleteTool,
    FileReadTool,
    FileWriteTool,
    ListDirTool,
)
from secretary.agent.tools.shell import (
    ShellTool,
    _infer_shell_call_from_text,
    _is_read_only_shell_command,
)
from secretary.agent.tools.web import WebFetchTool
from secretary.exceptions import AgentError
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)

MAX_LOOP_STEPS = 12
MAX_TOOL_OUTPUT_CHARS = 4000
_PROGRESS_DETAIL_LIMIT = 320

# Read / query tools never pause for user confirmation (Claude Code / OpenCode policy).
_READ_ONLY_TOOL_NAMES = frozenset(
    {
        "list_dir",
        "file_read",
        "search_files",
        "glob_files",
        "search_memory",
        "session_search",
        "web_search",
        "web_fetch",
        "shibei_search",
        "shibei_list_sources",
        "list_connectors",
        "connector_status",
        "skills_list",
        "skill_view",
        "clarify",
        "ask_user",
        "todo",
        "browser_open",
        "browser_snapshot",
        "browser_screenshot",
        "browser_click",
        "browser_fill",
        "browser_close",
    }
)


def _progress_detail_preview(text: str, limit: int = _PROGRESS_DETAIL_LIMIT) -> str:
    cleaned = text.strip()
    if len(cleaned) > limit:
        return cleaned[:limit] + "…"
    return cleaned


def _tool_action_detail(tool: Any, arguments: dict[str, Any], working_dir: Path) -> str:
    try:
        return _progress_detail_preview(tool.describe_action(arguments, working_dir))
    except Exception:
        try:
            return _progress_detail_preview(json.dumps(arguments, ensure_ascii=False))
        except Exception:
            return ""

def ensure_tool_call_id(tool_call: ToolCall, *, suffix: str) -> ToolCall:
    call_id = tool_call.id.strip()
    if call_id:
        return tool_call
    return ToolCall(
        name=tool_call.name,
        arguments=tool_call.arguments,
        id=f"call_{tool_call.name}_{suffix}",
    )


def assistant_message_for_tool_call(
    assistant_message: dict[str, Any],
    tool_call: ToolCall,
) -> dict[str, Any]:
    """Build an assistant message paired with exactly one tool response."""
    content = assistant_message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                },
            }
        ],
    }


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
    pending_step: StepResult | None = None
    messages_snapshot: list[dict[str, Any]] | None = None
    pause_assistant_message: dict[str, Any] | None = None
    pause_native_used: bool = False
    grounding_verified: bool = True
    grounding_note: str = ""
    files_read: list[str] = field(default_factory=list)


@dataclass
class PendingConfirmation:
    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    description: str
    risk_level: str
    confirmation_kind: str = "action"


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
        on_subagent_paused: Callable[[Any], None] | None = None,
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
        self._native_tools_enabled = True
        self._on_subagent_paused = on_subagent_paused

    def run(self, messages: list[dict[str, str]], temperature: float = 0.7) -> LoopResult:
        steps: list[StepResult] = []
        used_tools: list[str] = []
        current_messages = list(messages)
        raw = ""
        thought = ""
        grounding_retries = 0
        max_grounding_retries = 2
        web_retries = 0
        max_web_retries = 2
        verify_retries = 0
        max_verify_retries = 1
        auto_list_dir_used = False
        preflight_list_dir_used = False
        turn_user_message = resolve_turn_user_message(current_messages)

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
                ProgressEvent(
                    kind="iteration_started",
                    iteration=iteration,
                    message=f"第 {iteration}/{self._max_steps} 轮思考",
                )
            )
            tool_schemas = [t.schema() for t in self._tools.values()]
            payload = self._build_payload(current_messages, tool_schemas, native=self._native_tools_enabled)
            force_read = requires_forced_read_tool(turn_user_message, used_tools)
            needs_preflight = (
                step_idx == 0
                and not preflight_list_dir_used
                and not has_read_grounding(used_tools)
                and is_filesystem_question(turn_user_message)
                and "list_dir" in self._tools
            )
            if needs_preflight:
                target = infer_list_dir_target(turn_user_message)
                if target:
                    preflight_list_dir_used = True
                    auto_list_dir_used = True
                    list_tool = self._tools["list_dir"]
                    list_args = {"path": target}
                    try:
                        list_output = list_tool.execute(list_args, self._working_dir)
                    except Exception as exc:
                        list_output = f"Error: {exc}"
                    list_call = ToolCall(
                        name="list_dir",
                        arguments=list_args,
                        id="call_preflight_list_dir",
                    )
                    steps.append(
                        StepResult(
                            thought="",
                            tool_call=list_call,
                            tool_output=list_output,
                        )
                    )
                    used_tools.append("list_dir")
                    self._emit_progress(
                        ProgressEvent(
                            kind="tool_started",
                            iteration=iteration,
                            tool_name="list_dir",
                            detail=_tool_action_detail(list_tool, list_args, self._working_dir),
                        )
                    )
                    self._emit_progress(
                        ProgressEvent(
                            kind="tool_finished",
                            iteration=iteration,
                            tool_name="list_dir",
                            success=not str(list_output).startswith("Error:"),
                        )
                    )
                    current_messages.append({
                        "role": "user",
                        "content": (
                            f"[System] list_dir 已执行: {target}\n"
                            f"{list_output}\n"
                            "请根据以上真实列表直接回答用户，禁止说「稍等」或声称无读权限。"
                        ),
                    })
                    force_read = False

            block_stream = force_read or (
                is_filesystem_question(turn_user_message)
                and not has_read_grounding(used_tools)
            )
            on_delta = None if block_stream else self._build_reply_delta_callback(iteration)

            raw, tool_call, assistant_message, native_used = self._invoke_model(
                payload,
                tool_schemas,
                force_read=force_read,
                temperature=temperature,
                on_delta=on_delta,
            )
            if on_delta is not None:
                self._emit_progress(ProgressEvent(kind="reply_end", iteration=iteration))

            thought = raw.strip() if raw else ""
            if tool_call is None and raw:
                thought, fence_call = self._parse_response(raw)
                if fence_call is not None:
                    tool_call = fence_call

            if tool_call is None:
                reply = self._sanitize_reply(thought, snapshot)
                reply = sanitize_filesystem_reply(reply)
                if (
                    not auto_list_dir_used
                    and not has_read_grounding(used_tools)
                    and is_filesystem_question(turn_user_message)
                    and reply_defers_filesystem_work(reply)
                    and "list_dir" in self._tools
                ):
                    target = infer_list_dir_target(turn_user_message, reply)
                    if target:
                        auto_list_dir_used = True
                        list_tool = self._tools["list_dir"]
                        list_args = {"path": target}
                        try:
                            list_output = list_tool.execute(list_args, self._working_dir)
                        except Exception as exc:
                            list_output = f"Error: {exc}"
                        list_call = ToolCall(
                            name="list_dir",
                            arguments=list_args,
                            id=f"call_auto_list_dir_{step_idx}",
                        )
                        steps.append(
                            StepResult(
                                thought=thought,
                                tool_call=list_call,
                                tool_output=list_output,
                            )
                        )
                        used_tools.append("list_dir")
                        self._emit_progress(
                            ProgressEvent(
                                kind="tool_started",
                                iteration=iteration,
                                tool_name="list_dir",
                                detail=_tool_action_detail(list_tool, list_args, self._working_dir),
                            )
                        )
                        self._emit_progress(
                            ProgressEvent(
                                kind="tool_finished",
                                iteration=iteration,
                                tool_name="list_dir",
                                success=not str(list_output).startswith("Error:"),
                            )
                        )
                        self._append_tool_result_messages(
                            current_messages,
                            raw=raw or f"[auto] list_dir {target}",
                            tool_call=list_call,
                            tool_output=list_output,
                            assistant_message=assistant_message,
                            native_used=native_used,
                            step_idx=step_idx,
                        )
                        continue

                if (
                    grounding_retries < max_grounding_retries
                    and should_retry_for_grounding(
                        turn_user_message, reply, used_tools
                    )
                ):
                    grounding_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append({"role": "user", "content": GROUNDING_RETRY_USER})
                    continue

                from secretary.agent.web_research import (
                    WEB_RETRY_USER,
                    should_retry_for_web_research,
                )

                if (
                    web_retries < max_web_retries
                    and should_retry_for_web_research(
                        turn_user_message, reply, used_tools
                    )
                ):
                    web_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append({"role": "user", "content": WEB_RETRY_USER})
                    continue

                evidence = collect_read_evidence(steps)
                command_evidence = collect_command_evidence(steps)
                verification = verify_reply_against_evidence(
                    reply,
                    evidence,
                    turn_user_message,
                    command_evidence=command_evidence,
                )
                from secretary.services.shibei_service import is_shibei_empty_result

                shibei_empty = any(
                    step.tool_call
                    and step.tool_call.name == "shibei_search"
                    and step.tool_output
                    and is_shibei_empty_result(str(step.tool_output))
                    for step in steps
                )
                if (
                    verify_retries < max_verify_retries
                    and should_retry_for_verification(verification)
                    and not shibei_empty
                ):
                    verify_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": format_verify_retry(
                                verification, evidence, command_evidence=command_evidence
                            ),
                        }
                    )
                    continue

                files_read = sorted(evidence.read_files | evidence.search_hits)
                final_reply, verified, note = enforce_grounded_reply(
                    reply,
                    turn_user_message,
                    used_tools,
                    grounding_verified=verification.ok,
                    grounding_note=verification.note,
                    command_evidence=command_evidence,
                )
                self._emit_progress(
                    ProgressEvent(
                        kind="iteration_completed",
                        iteration=iteration,
                        message="核实通过，停止循环",
                        success=True,
                    )
                )
                self._emit_progress(
                    ProgressEvent(kind="final_reply", iteration=iteration, message=final_reply)
                )
                return LoopResult(
                    reply=final_reply,
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx + 1,
                    grounding_verified=verified,
                    grounding_note=note,
                    files_read=files_read,
                )

            tool = self._tools.get(tool_call.name)
            if tool is None:
                tool_output = f"Error: unknown tool '{tool_call.name}'"
                step = StepResult(thought=thought, tool_call=tool_call, tool_output=tool_output)
                steps.append(step)
                self._append_tool_result_messages(
                    current_messages,
                    raw=raw,
                    tool_call=tool_call,
                    tool_output=tool_output,
                    assistant_message=assistant_message,
                    native_used=native_used,
                    step_idx=step_idx,
                )
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
                    pending_step=step,
                    messages_snapshot=list(current_messages),
                )

            try:
                args_detail = _tool_action_detail(tool, tool_call.arguments, self._working_dir)
                thought_detail = _progress_detail_preview(thought) if thought.strip() else ""
                if thought_detail and args_detail:
                    combined_detail = f"{thought_detail}\n\n{args_detail}"
                else:
                    combined_detail = thought_detail or args_detail
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_started",
                        iteration=iteration,
                        tool_name=tool_call.name,
                        detail=combined_detail,
                    )
                )
                if hasattr(tool, "bind_progress"):
                    tool.bind_progress(self._progress_callback)
                tool_output = tool.execute(tool_call.arguments, self._working_dir)
                used_tools.append(tool_call.name)
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_finished",
                        iteration=iteration,
                        tool_name=tool_call.name,
                        success=True,
                        detail=_progress_detail_preview(tool_output),
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
                        detail=_progress_detail_preview(tool_output),
                    )
                )

            if len(tool_output) > MAX_TOOL_OUTPUT_CHARS:
                tool_output = tool_output[:MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"

            if tool_call.name == "spawn_subagent" and hasattr(tool, "consume_paused"):
                paused = tool.consume_paused()
                if paused is not None and self._on_subagent_paused is not None:
                    self._on_subagent_paused(paused)
                    step = StepResult(
                        thought=thought,
                        tool_call=tool_call,
                        tool_output=f"[Sub-agent paused for confirmation] {paused.pending.description}",
                        needs_confirmation=True,
                    )
                    steps.append(step)
                    return LoopResult(
                        reply=(
                            f"子 Agent ({paused.archetype}) 需要你的确认：\n\n"
                            f"{paused.pending.description}\n\n是否允许？"
                        ),
                        steps=steps,
                        used_tools=used_tools,
                        total_steps=step_idx + 1,
                        pending_confirmation=paused.pending,
                        pending_step=step,
                        messages_snapshot=list(current_messages),
                        pause_assistant_message=assistant_message,
                        pause_native_used=native_used,
                    )

            step = StepResult(thought=thought, tool_call=tool_call, tool_output=tool_output)
            steps.append(step)

            from secretary.agent.p0_tools import format_user_input_reply, is_user_input_request

            if is_user_input_request(tool_output):
                clarify_reply = format_user_input_reply(tool_output, thought=thought)
                reply = self._sanitize_reply(clarify_reply or thought, snapshot)
                self._emit_progress(
                    ProgressEvent(
                        kind="iteration_completed",
                        iteration=iteration,
                        message="需要澄清，停止循环",
                        success=True,
                    )
                )
                self._emit_progress(
                    ProgressEvent(kind="final_reply", iteration=iteration, message=reply)
                )
                return LoopResult(
                    reply=reply,
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx + 1,
                )

            self._append_tool_result_messages(
                current_messages,
                raw=raw,
                tool_call=tool_call,
                tool_output=tool_output,
                assistant_message=assistant_message,
                native_used=native_used,
                step_idx=step_idx,
            )

        snapshot = LoopSnapshot(
            iteration=self._max_steps,
            max_iterations=self._max_steps,
            latest_user_message=self._latest_user_message(current_messages),
        )

        # When max steps reached with tool evidence, make one final call
        # without tools to produce a coherent answer from collected evidence.
        if steps:
            try:
                self._emit_progress(
                    ProgressEvent(
                        kind="iteration_started",
                        iteration=self._max_steps,
                        message="整理回复",
                    )
                )
                summary_prompt = (
                    "你已用完所有工具轮次。请基于以上所有工具返回的结果，"
                    "给用户一个完整的最终回答。不要调用工具，直接回答。"
                )
                current_messages.append({"role": "user", "content": summary_prompt})
                payload = self._build_payload(current_messages, tool_schemas=[], native=False)
                raw = chat_completion(
                    self._llm_config, payload, temperature=temperature, timeout=120.0
                )
                thought = raw.strip()
            except Exception:
                pass

        reply = self._sanitize_reply(thought if steps else raw, snapshot)
        # Strip receipt tags and enforce command receipts on the max-steps path too.
        from secretary.agent.grounding import (
            UNGROUNDED_COMMAND_FALLBACK,
            extract_receipt_refs,
            reply_claims_or_simulates_command_execution,
            strip_receipt_tags,
        )

        command_evidence = collect_command_evidence(steps)
        if reply_claims_or_simulates_command_execution(reply):
            refs = extract_receipt_refs(reply)
            if not refs or (refs - command_evidence.receipt_ids):
                reply = UNGROUNDED_COMMAND_FALLBACK
        reply = strip_receipt_tags(reply)
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

    def resume_after_confirmation(
        self,
        pending: PendingConfirmation,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
    ) -> LoopResult:
        """Execute a confirmed tool and continue the agent loop (Codex turn-resume)."""
        tool = self._tools.get(pending.tool_name)
        if tool is None:
            return LoopResult(reply="Error: tool no longer available", steps=[], used_tools=[], total_steps=0)

        try:
            tool_output = tool.execute(pending.arguments, self._working_dir)
        except Exception as exc:
            tool_output = f"Error: {exc}"

        if len(tool_output) > MAX_TOOL_OUTPUT_CHARS:
            tool_output = tool_output[:MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"

        continued = list(messages)
        continued.append({
            "role": "user",
            "content": (
                f"[User confirmed: {pending.description}]\n"
                f"[Tool Result: {pending.tool_name}]\n{tool_output}"
            ),
        })
        result = self.run(continued, temperature=temperature)
        if pending.tool_name not in result.used_tools:
            result.used_tools.insert(0, pending.tool_name)
        return result

    def resume_after_subagent_tool(
        self,
        messages: list[dict[str, Any]],
        *,
        thought: str,
        tool_call: ToolCall,
        tool_output: str,
        assistant_message: dict[str, Any] | None,
        native_used: bool,
        step_idx: int,
        temperature: float = 0.7,
    ) -> LoopResult:
        """Append a completed spawn_subagent result and continue the parent loop."""
        current_messages = list(messages)
        self._append_tool_result_messages(
            current_messages,
            raw=thought,
            tool_call=tool_call,
            tool_output=tool_output,
            assistant_message=assistant_message,
            native_used=native_used,
            step_idx=step_idx,
        )
        result = self.run(current_messages, temperature=temperature)
        if "spawn_subagent" not in result.used_tools:
            result.used_tools.insert(0, "spawn_subagent")
        return result

    def _requires_confirmation(
        self,
        tool: Tool,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        if tool.name in _READ_ONLY_TOOL_NAMES:
            return False, ""
        if tool.name.startswith("mcp_"):
            from secretary.agent.mcp_manager import mcp_tool_needs_confirmation

            if not mcp_tool_needs_confirmation(tool.name):
                return False, ""

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

    def _build_reply_delta_callback(self, iteration: int) -> Callable[[str], None] | None:
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

    def _invoke_model(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        *,
        force_read: bool,
        temperature: float,
        on_delta: Callable[[str], None] | None,
    ) -> tuple[str, ToolCall | None, dict[str, Any] | None, bool]:
        if self._native_tools_enabled and tool_schemas:
            read_schemas = self._read_tool_schemas(tool_schemas)
            active_schemas = read_schemas if force_read and read_schemas else tool_schemas
            openai_tools = schemas_to_openai_tools(active_schemas)
            if openai_tools:
                tool_choice: str | dict[str, Any] = "required" if force_read else "auto"
                try:
                    result = chat_completion_with_tools(
                        self._llm_config,
                        messages,
                        openai_tools,
                        tool_choice=tool_choice,
                        temperature=temperature,
                        timeout=180.0,
                    )
                    tool_call = self._tool_call_from_result(result)
                    return result.content, tool_call, result.assistant_message, True
                except (AgentError, TypeError, ValueError) as error:
                    logger.warning("Native tool calling unavailable, falling back: %s", error)
                    self._native_tools_enabled = False

        raw = chat_completion(
            self._llm_config,
            messages,
            temperature=temperature,
            timeout=180.0,
            on_delta=on_delta,
        )
        thought, tool_call = self._parse_response(raw)
        return raw, tool_call, {"role": "assistant", "content": raw}, False

    def _tool_call_from_result(self, result: ChatCompletionResult) -> ToolCall | None:
        if not result.tool_calls:
            return None
        if len(result.tool_calls) > 1:
            logger.info(
                "Model returned %s tool calls in one step; executing the first only",
                len(result.tool_calls),
            )
        first = result.tool_calls[0]
        return ToolCall(name=first.name, arguments=first.arguments, id=first.id)

    def _append_tool_result_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        raw: str,
        tool_call: ToolCall,
        tool_output: str,
        assistant_message: dict[str, Any] | None,
        native_used: bool,
        step_idx: int,
    ) -> None:
        paired_call = ensure_tool_call_id(tool_call, suffix=str(step_idx))
        # Inject receipt header for shell commands so the LLM can cite execution
        # in its final reply via [receipt:<id>].
        if paired_call.name == "shell":
            tool_output = f"[receipt:{paired_call.id}]\n{tool_output}"
        if native_used and assistant_message is not None:
            self._append_tool_exchange(
                messages,
                assistant_message=assistant_message,
                tool_call=paired_call,
                tool_output=tool_output,
            )
            return
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": f"[Tool Result: {paired_call.name}]\n{tool_output}",
        })

    def _append_tool_exchange(
        self,
        messages: list[dict[str, Any]],
        *,
        assistant_message: dict[str, Any],
        tool_call: ToolCall,
        tool_output: str,
    ) -> None:
        messages.append(assistant_message_for_tool_call(assistant_message, tool_call))
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_output,
            }
        )

    def _read_tool_schemas(self, tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from secretary.agent.grounding import READ_TOOL_NAMES

        read: list[dict[str, Any]] = []
        for schema in tool_schemas:
            name = str(schema.get("name") or "")
            if name in READ_TOOL_NAMES:
                read.append(schema)
                continue
            lowered = name.lower()
            if name.startswith("mcp_") and any(
                hint in lowered for hint in ("read", "list", "search", "glob", "directory", "file")
            ):
                read.append(schema)
        return read

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        tool_schemas: list[dict[str, Any]],
        *,
        native: bool = False,
    ) -> list[dict[str, str]]:
        tools_desc = json.dumps(tool_schemas, ensure_ascii=False, indent=2)
        tool_names = ", ".join(self._tools.keys())
        if native:
            instruction = (
                "You have access to function tools (native tool calling).\n"
                f"Available tools: {tool_names}\n\n"
                f"Tool schemas:\n{tools_desc}\n\n"
                "Rules:\n"
                "- For local files, directories, or project structure: call list_dir, file_read, or search_files BEFORE answering.\n"
                "- Never invent file paths, filenames, or file contents.\n"
                "- Never paste simulated `$ ls`, `total N`, permission lines, or directory trees (├──) in your reply.\n"
                "- Never tell the user Lumina lacks read permission; list_dir names are enough for project lists; use file_read for contents.\n"
                "- In final answers, only mention files that appeared in tool results.\n"
                "- Use one tool call per step.\n"
                "- Write tools (file_write, patch, file_delete, shell) need user confirmation.\n"
                "- Shell tool results include a `[receipt:<id>]` header. When your final reply claims to have "
                "run a command or cites its output, append `[receipt:<id>]` after that claim. "
                "Never describe a command as 'executed/run/passed' unless it went through the shell tool this turn. "
                "Never paste simulated shell output (e.g. `$ cmd\\noutput`, `===== N failed =====`, `exit code: N`) "
                "without a real receipt — call the shell tool instead.\n"
            )
        else:
            instruction = (
                "You have access to the following tools. "
                "To use a tool, output a JSON block inside ```tool-call``` fences:\n"
                "```tool-call\n"
                '{"name": "<tool_name>", "arguments": {<args>}}\n'
                "```\n\n"
                f"Available tools: {tool_names}\n\n"
                f"Tool schemas:\n{tools_desc}\n\n"
                "Rules:\n"
                "- If you can answer directly without tools, do so — EXCEPT for local files, directories, or project structure.\n"
                "- For anything about the user's filesystem or codebase: ALWAYS call list_dir, file_read, or search_files first.\n"
                "- Never invent file paths, filenames, or file contents. If you have not read a file, say you have not verified it.\n"
                "- Never paste simulated `$ ls`, directory trees (├──), or fake command output in your reply.\n"
                "- Use only one tool per step.\n"
                "- After receiving tool results, decide if you need more steps or can answer.\n"
                "- When done, provide the final answer without any tool-call blocks.\n"
                "- Read tools (file_read, list_dir, search_files) execute immediately without confirmation.\n"
                "- Never claim you can only see directory structure — list_dir already returns real file and folder names.\n"
                "- New files can be created without repeated prompts after session write authorization.\n"
                "- Modifying or deleting files always needs user confirmation.\n"
                "- Write tools (file_write, patch, file_delete, shell) follow the authorization rules above.\n"
                "- Shell tool results include a `[receipt:<id>]` header. When your final reply claims to have "
                "run a command or cites its output, append `[receipt:<id>]` after that claim. "
                "Never describe a command as 'executed/run/passed' unless it went through the shell tool this turn. "
                "Never paste simulated shell output (e.g. `$ cmd\\noutput`, `===== N failed =====`, `exit code: N`) "
                "without a real receipt — call the shell tool instead.\n"
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


