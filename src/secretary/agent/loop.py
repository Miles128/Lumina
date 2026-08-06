"""Agent Loop: plan → act → observe → reflect cycle.

Read tools (file_read, list_dir) execute immediately.
Write tools (file_write, shell) require user confirmation via pending_actions.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from secretary.agent.artifact_paths import collect_artifact_paths
from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.context_compaction import compact_messages_if_needed
from secretary.agent.grounding import (
    CONTENT_GROUNDING_RETRY_USER,
    GROUNDING_RETRY_USER,
    collect_command_evidence,
    collect_read_evidence,
    enforce_grounded_reply,
    format_verify_retry,
    has_content_grounding,
    has_read_grounding,
    infer_list_dir_target,
    is_file_content_question,
    is_filesystem_question,
    reply_defers_filesystem_work,
    requires_forced_content_read,
    requires_forced_read_tool,
    resolve_turn_user_message,
    sanitize_filesystem_reply,
    should_retry_for_grounding,
    should_retry_for_verification,
    verify_reply_against_evidence,
)
from secretary.agent.harness_config import ConfirmRequireConfig
from secretary.agent.lifecycle_hooks import (
    AfterToolContext,
    AfterToolExecutionHook,
    BeforeModelCallHook,
    BeforeToolExecutionHook,
    BeforeTurnHook,
    HookDecision,
    ModelCallContext,
    ToolExecContext,
    TurnContext,
)
from secretary.agent.llm_client import (
    ChatCompletionResult,
    chat_completion,
    chat_completion_with_tools,
    llm_usage_scope,
    schemas_to_openai_tools,
)
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop_messages import (
    assistant_message_for_batch,
    assistant_message_for_tool_call,
    classify_tool_error,
    ensure_tool_call_id,
    wrap_untrusted,
)
from secretary.agent.loop_prompting import (
    build_cached_instruction,
    build_payload,
    parse_tool_call_response,
)
from secretary.agent.progress_events import ProgressEvent, emit_progress
from secretary.agent.stop_hooks import (
    LoopSnapshot,
    MaxIterationsStopHook,
    StopDecision,
    StopHook,
    ThirdPersonMetaReplyStopHook,
)
from secretary.agent.text_utils import truncate_chars
from secretary.agent.tools.base import (
    Tool,
    ToolCall,
    ToolResult,
    _coerce_to_tool_result,
)
from secretary.agent.tools.fs import (
    FileDeleteTool,
    FileReadTool,
    FileWriteTool,
    ListDirTool,
)
from secretary.agent.tools.shell import ShellTool
from secretary.agent.tools.web import WebFetchTool
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)

MAX_LOOP_STEPS = 20
MAX_TOOL_OUTPUT_CHARS = 4000
_PROGRESS_DETAIL_LIMIT = 320

# Back-compat aliases for callers that imported private helpers from loop.
_wrap_untrusted = wrap_untrusted
_classify_tool_error = classify_tool_error


def _progress_detail_preview(text: str, limit: int = _PROGRESS_DETAIL_LIMIT) -> str:
    cleaned = text.strip()
    if len(cleaned) > limit:
        return cleaned[:limit] + "…"
    return cleaned


def _combine_thought_and_args_detail(thought: str, args_detail: str) -> str:
    """Keep full thought text; truncate only the tool-args preview portion.

    When thought is present, always use a blank-line separator so the UI can
    peel the thought node even if args are empty.
    """
    thought_detail = thought.strip()
    args_preview = _progress_detail_preview(args_detail) if args_detail.strip() else ""
    if thought_detail:
        return f"{thought_detail}\n\n{args_preview}"
    return args_preview


def _tool_action_detail(tool: Any, arguments: dict[str, Any], working_dir: Path) -> str:
    try:
        return _progress_detail_preview(tool.describe_action(arguments, working_dir))
    except Exception:
        try:
            return _progress_detail_preview(json.dumps(arguments, ensure_ascii=False))
        except Exception:
            return ""


def _pending_tool_call_id(messages: list[dict[str, Any]], tool_name: str) -> str | None:
    """Return an unanswered native tool_call id for ``tool_name`` after the last assistant."""
    answered: set[str] = set()
    last_assistant_idx = -1
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant" and isinstance(message.get("tool_calls"), list):
            last_assistant_idx = index
        elif role == "tool":
            call_id = str(message.get("tool_call_id") or "").strip()
            if call_id:
                answered.add(call_id)
    if last_assistant_idx < 0:
        return None
    tool_calls = messages[last_assistant_idx].get("tool_calls")
    if not isinstance(tool_calls, list):
        return None
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        name = ""
        if isinstance(function, dict):
            name = str(function.get("name") or "")
        elif call.get("name"):
            name = str(call.get("name") or "")
        call_id = str(call.get("id") or "").strip()
        if name == tool_name and call_id and call_id not in answered:
            return call_id
    return None


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
    cancelled: bool = False
    pending_confirmation: PendingConfirmation | None = None
    pending_step: StepResult | None = None
    messages_snapshot: list[dict[str, Any]] | None = None
    pause_assistant_message: dict[str, Any] | None = None
    pause_native_used: bool = False
    grounding_verified: bool = True
    grounding_note: str = ""
    files_read: list[str] = field(default_factory=list)
    # execute_confirmed 中 LLM 返回了新的 tool_call 但未执行时，记录在此供
    # 调用方感知（不会写入 steps/used_tools，避免误以为已执行）。
    pending_tool_call: ToolCall | None = None


@dataclass
class PendingConfirmation:
    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    description: str
    risk_level: str
    confirmation_kind: str = "action"
    diff_preview: str = ""


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
        cancel_check: Callable[[], bool] | None = None,
        before_turn_hooks: list[BeforeTurnHook] | None = None,
        before_model_call_hooks: list[BeforeModelCallHook] | None = None,
        before_tool_execution_hooks: list[BeforeToolExecutionHook] | None = None,
        after_tool_execution_hooks: list[AfterToolExecutionHook] | None = None,
        force_web_first_step: bool = False,
        explicit_working_dir: bool = False,
        compaction_max_tokens: int | None = None,
        compaction_keep_tail: int | None = None,
        thinking: str = "enabled",
        reasoning_effort: str | None = "high",
        strict_tools: bool = False,
        require_confirm: ConfirmRequireConfig | None = None,
        max_tool_output_chars: int | None = None,
    ) -> None:
        self._llm_config = llm_config
        raw_tools = list(tools or _default_tools())
        self._tools = _index_tools(raw_tools)
        self._max_steps = max_steps
        self._working_dir = (working_dir or Path.home()).expanduser().resolve()
        if not self._working_dir.is_dir():
            self._working_dir = Path.home()
        self._file_auth = file_auth
        self._require_confirm = require_confirm
        self._stop_hooks = stop_hooks or [
            MaxIterationsStopHook(max_steps),
            ThirdPersonMetaReplyStopHook(),
        ]
        self._progress_callback = progress_callback
        self._native_tools_enabled = True
        self._on_subagent_paused = on_subagent_paused
        self._cancel_check = cancel_check
        self._cancelled = False
        self._before_turn_hooks = before_turn_hooks or []
        self._before_model_call_hooks = before_model_call_hooks or []
        self._before_tool_execution_hooks = before_tool_execution_hooks or []
        self._after_tool_execution_hooks = after_tool_execution_hooks or []
        self._force_web_first_step = force_web_first_step
        self._web_forced_used = False
        self._explicit_working_dir = explicit_working_dir
        self._compaction_max_tokens = compaction_max_tokens
        self._compaction_keep_tail = compaction_keep_tail
        self._thinking = thinking
        self._reasoning_effort = reasoning_effort
        self._strict_tools = strict_tools
        # FR-52: harness.max_tool_output_chars overrides the module default;
        # keeps hard truncation aligned with the TruncateToolOutputHook limit.
        self._tool_output_limit = (
            MAX_TOOL_OUTPUT_CHARS
            if max_tool_output_chars is None
            else max_tool_output_chars
        )
        # Cache tool schemas once from the concrete tool list (not alias index),
        # so legacy lookup aliases do not duplicate schemas sent to the model.
        self._tool_schemas: list[dict[str, Any]] = [t.schema() for t in raw_tools]
        self._tool_names = ", ".join(t.name for t in raw_tools)
        # NOTE: _instruction_cache 不加锁。AgentLoop 实例不应被多线程并发使用
        # （run() 是有状态的同步循环，共享 _cancelled / messages / steps 等）。
        # 如未来需要并发复用同一实例，应改用 threading.Lock 保护缓存写入，
        # 或在外层通过每线程独立实例来隔离状态。
        self._instruction_cache: dict[bool, str] = {}

    def _resolved_thinking(self) -> Literal["enabled", "disabled"]:
        if self._thinking == "disabled":
            return "disabled"
        return "enabled"

    def cancel(self) -> None:
        """协作式取消：设置标志，loop 在下一轮迭代开头检测并退出。"""
        self._cancelled = True

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
        # Shared retry budget: grounding + web + verify retries collectively
        # cannot exceed this, preventing worst-case 5 extra iterations (2+2+1)
        # from exhausting the 12-step ceiling.
        shared_retries = 0
        max_shared_retries = 3
        auto_list_dir_used = False
        preflight_list_dir_used = False
        turn_user_message = resolve_turn_user_message(current_messages)

        for step_idx in range(self._max_steps):
            iteration = step_idx + 1
            if self._is_cancelled():
                return self._cancelled_result(steps, used_tools, step_idx)
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
            # 生命周期钩子：BeforeTurn
            turn_decision = self._run_before_turn_hooks(snapshot, current_messages)
            if turn_decision.should_skip:
                logger.info("BeforeTurn hook skipped iteration %d: %s", iteration, turn_decision.reason)
                continue

            self._emit_progress(
                ProgressEvent(
                    kind="iteration_started",
                    iteration=iteration,
                )
            )
            compact_kwargs: dict[str, Any] = {}
            if self._compaction_max_tokens is not None:
                compact_kwargs["max_tokens"] = self._compaction_max_tokens
            if self._compaction_keep_tail is not None:
                compact_kwargs["keep_tail"] = self._compaction_keep_tail
            compaction = compact_messages_if_needed(
                current_messages, self._llm_config, **compact_kwargs
            )
            current_messages = compaction.messages
            if compaction.triggered:
                self._emit_progress(
                    ProgressEvent(
                        kind="context_compacted",
                        iteration=iteration,
                        message=(
                            f"上下文已压缩：{compaction.before_tokens}→"
                            f"{compaction.after_tokens} tokens ({compaction.mode})"
                        ),
                        detail=compaction.to_detail(),
                        prompt_tokens=compaction.before_tokens,
                        completion_tokens=compaction.after_tokens,
                    )
                )
            payload = self._build_payload(current_messages, self._tool_schemas, native=self._native_tools_enabled)
            force_content = requires_forced_content_read(turn_user_message, used_tools)
            force_read = force_content or requires_forced_read_tool(
                turn_user_message, used_tools
            )
            needs_preflight = (
                step_idx == 0
                and not preflight_list_dir_used
                and not has_read_grounding(used_tools)
                and not force_content  # 内容问题直接强制 file_read，跳过仅 list_dir 预飞
                and "list_dir" in self._tools
                and (
                    is_filesystem_question(turn_user_message)
                    or self._explicit_working_dir
                )
            )
            if needs_preflight:
                target = infer_list_dir_target(turn_user_message) or str(self._working_dir)
                if target:
                    preflight_list_dir_used = True
                    auto_list_dir_used = True
                    preflight_outcome = self._run_injected_tool(
                        tool_name="list_dir",
                        arguments={"path": target},
                        iteration=iteration,
                        step_idx=step_idx,
                        call_id="call_preflight_list_dir",
                        thought="",
                        steps=steps,
                        used_tools=used_tools,
                    )
                    if isinstance(preflight_outcome, LoopResult):
                        return preflight_outcome
                    _preflight_call, list_output = preflight_outcome
                    # Just-in-Time 检索：只注入轻量摘要（路径 + 条目数），不预载完整列表。
                    # LLM 可按需调用 list_dir/file_read 获取详细内容，避免上下文膨胀。
                    _list_success = not str(list_output).startswith("Error:")
                    if _list_success:
                        _entry_count = list_output.count("\n") + 1
                        if self._explicit_working_dir:
                            _preview_lines = list_output.splitlines()
                            _MAX_PREVIEW = 60
                            _MAX_CHARS = 2000
                            _preview = "\n".join(_preview_lines[:_MAX_PREVIEW])
                            if len(_preview) > _MAX_CHARS:
                                _preview = _preview[:_MAX_CHARS].rstrip() + "\n…（已截断）"
                            elif len(_preview_lines) > _MAX_PREVIEW:
                                _preview = (
                                    _preview.rstrip()
                                    + f"\n…（还有 {len(_preview_lines) - _MAX_PREVIEW} 项，可用 list_dir 查看）"
                                )
                            current_messages.append({
                                "role": "user",
                                "content": (
                                    f"[System] 已预读工作区 {target}（{_entry_count} 项），顶层条目如下：\n"
                                    f"{_preview}\n"
                                    "回答可直接引用上述真实文件/目录名；如需文件内容再调用 file_read。"
                                    "禁止编造未出现在上面的路径或文件名，禁止声称无读权限。"
                                ),
                            })
                        else:
                            current_messages.append({
                                "role": "user",
                                "content": (
                                    f"[System] list_dir 已执行: {target}（{_entry_count} 项）\n"
                                    "如需查看具体文件名或进一步读取内容，请调用 list_dir 或 file_read 工具。"
                                    "禁止说「稍等」或声称无读权限。"
                                ),
                            })
                    else:
                        current_messages.append({
                            "role": "user",
                            "content": (
                                f"[System] list_dir 执行失败: {target}\n"
                                f"{list_output}\n"
                                "请换一种路径或方式回答用户。"
                            ),
                        })
                    # 内容类问题：list_dir 预飞后仍强制 file_read，不准直接答。
                    force_content = requires_forced_content_read(
                        turn_user_message, used_tools
                    )
                    force_read = force_content or requires_forced_read_tool(
                        turn_user_message, used_tools
                    )

            block_stream = force_read or force_content or (
                is_filesystem_question(turn_user_message)
                and not has_read_grounding(used_tools)
            ) or (
                is_file_content_question(turn_user_message)
                and not has_content_grounding(used_tools)
            )
            on_delta = None if block_stream else self._build_reply_delta_callback(iteration)

            # 生命周期钩子：BeforeModelCall
            self._run_before_model_call_hooks(snapshot, payload, self._tool_schemas, temperature)

            # 协作式取消：在 LLM 调用前再次检查，避免取消后仍发起一次昂贵的网络请求。
            if self._is_cancelled():
                return self._cancelled_result(steps, used_tools, step_idx)

            # 全链路可观测性：LLM 调用计时 + token 计数
            _llm_start = time.perf_counter()
            with llm_usage_scope() as _step_usage:
                raw, tool_calls, assistant_message, native_used = self._invoke_model(
                    payload,
                    self._tool_schemas,
                    force_read=force_read,
                    force_content=force_content,
                    temperature=temperature,
                    on_delta=on_delta,
                )
            _llm_latency_ms = int((time.perf_counter() - _llm_start) * 1000)
            if on_delta is not None:
                self._emit_progress(
                    ProgressEvent(
                        kind="reply_end",
                        iteration=iteration,
                        latency_ms=_llm_latency_ms,
                        prompt_tokens=_step_usage.prompt_tokens,
                        completion_tokens=_step_usage.completion_tokens,
                    )
                )

            thought = raw.strip() if raw else ""
            if not tool_calls and raw:
                thought, fence_call = self._parse_response(raw)
                if fence_call is not None:
                    tool_calls = [fence_call]

            if not tool_calls:
                tool_call = None
            elif len(tool_calls) > 1 and native_used:
                batch_outcome = self._run_native_tool_batch(
                    tool_calls,
                    assistant_message=assistant_message,
                    thought=thought,
                    raw=raw,
                    current_messages=current_messages,
                    steps=steps,
                    used_tools=used_tools,
                    iteration=iteration,
                    step_idx=step_idx,
                )
                if isinstance(batch_outcome, LoopResult):
                    return batch_outcome
                if batch_outcome is True:
                    continue
                tool_call = tool_calls[0]
            else:
                tool_call = tool_calls[0]

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
                    retry_target = infer_list_dir_target(turn_user_message, reply)
                    if retry_target:
                        auto_list_dir_used = True
                        list_outcome = self._run_injected_tool(
                            tool_name="list_dir",
                            arguments={"path": retry_target},
                            iteration=iteration,
                            step_idx=step_idx,
                            call_id=f"call_auto_list_dir_{step_idx}",
                            thought=thought,
                            steps=steps,
                            used_tools=used_tools,
                        )
                        if isinstance(list_outcome, LoopResult):
                            return list_outcome
                        auto_call, auto_output = list_outcome
                        self._append_tool_result_messages(
                            current_messages,
                            raw=raw or f"[auto] list_dir {retry_target}",
                            tool_call=auto_call,
                            tool_output=auto_output,
                            assistant_message=assistant_message,
                            native_used=native_used,
                            step_idx=step_idx,
                        )
                        continue

                # Safety net: LLM wrote "让我搜一下" but didn't call any web
                # tool. Inject a web_search to force grounding instead of
                # letting the turn end with an empty or hallucinated reply.
                from secretary.agent.web_research import reply_claims_web_search

                if (
                    shared_retries < max_shared_retries
                    and web_retries < max_web_retries
                    and "web_search" in self._tools
                    and reply_claims_web_search(reply, used_tools)
                ):
                    web_retries += 1
                    shared_retries += 1
                    web_outcome = self._run_injected_tool(
                        tool_name="web_search",
                        arguments={"query": turn_user_message.strip()[:200]},
                        iteration=iteration,
                        step_idx=step_idx,
                        call_id=f"call_auto_web_search_{step_idx}",
                        thought=thought,
                        steps=steps,
                        used_tools=used_tools,
                    )
                    if isinstance(web_outcome, LoopResult):
                        return web_outcome
                    web_call, web_output = web_outcome
                    self._append_tool_result_messages(
                        current_messages,
                        raw=raw or f"[auto] web_search {web_call.arguments['query']}",
                        tool_call=web_call,
                        tool_output=web_output,
                        assistant_message=assistant_message,
                        native_used=native_used,
                        step_idx=step_idx,
                    )
                    continue

                # Force web search when the router already judged needs_web=true
                # but the model still tried to end the turn without calling any
                # web tool (e.g. "有引用吗" → model restates old citations).
                # Fires once per turn; not gated by shared_retries because the
                # router's judgement is authoritative for this branch.
                from secretary.agent.web_research import _WEB_TOOL_NAMES

                if (
                    self._force_web_first_step
                    and not self._web_forced_used
                    and "web_search" in self._tools
                    and not any(
                        name in _WEB_TOOL_NAMES for name in used_tools
                    )
                ):
                    self._web_forced_used = True
                    web_outcome = self._run_injected_tool(
                        tool_name="web_search",
                        arguments={"query": turn_user_message.strip()[:200]},
                        iteration=iteration,
                        step_idx=step_idx,
                        call_id=f"call_force_web_{step_idx}",
                        thought=thought,
                        steps=steps,
                        used_tools=used_tools,
                    )
                    if isinstance(web_outcome, LoopResult):
                        return web_outcome
                    web_call, web_output = web_outcome
                    self._append_tool_result_messages(
                        current_messages,
                        raw=raw or f"[force] web_search {web_call.arguments['query']}",
                        tool_call=web_call,
                        tool_output=web_output,
                        assistant_message=assistant_message,
                        native_used=native_used,
                        step_idx=step_idx,
                    )
                    continue

                if (
                    shared_retries < max_shared_retries
                    and grounding_retries < max_grounding_retries
                    and should_retry_for_grounding(
                        turn_user_message, reply, used_tools
                    )
                ):
                    grounding_retries += 1
                    shared_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    retry_prompt = (
                        CONTENT_GROUNDING_RETRY_USER
                        if is_file_content_question(turn_user_message)
                        and not has_content_grounding(used_tools)
                        else GROUNDING_RETRY_USER
                    )
                    current_messages.append({"role": "user", "content": retry_prompt})
                    continue

                from secretary.agent.web_research import (
                    WEB_RETRY_USER,
                    should_retry_for_web_research,
                )

                if (
                    shared_retries < max_shared_retries
                    and web_retries < max_web_retries
                    and should_retry_for_web_research(
                        turn_user_message, reply, used_tools
                    )
                ):
                    web_retries += 1
                    shared_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append({"role": "user", "content": WEB_RETRY_USER})
                    continue

                from secretary.agent.knowledge_work import (
                    OFFICE_RETRY_USER,
                    RESEARCH_RETRY_USER,
                    should_retry_for_office,
                    should_retry_for_research_intent,
                )

                if (
                    shared_retries < max_shared_retries
                    and web_retries < max_web_retries
                    and should_retry_for_research_intent(
                        turn_user_message, reply, used_tools
                    )
                ):
                    web_retries += 1
                    shared_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append(
                        {"role": "user", "content": RESEARCH_RETRY_USER}
                    )
                    continue

                if (
                    shared_retries < max_shared_retries
                    and grounding_retries < max_grounding_retries
                    and should_retry_for_office(
                        turn_user_message, reply, used_tools
                    )
                ):
                    grounding_retries += 1
                    shared_retries += 1
                    current_messages.append({"role": "assistant", "content": raw})
                    current_messages.append(
                        {"role": "user", "content": OFFICE_RETRY_USER}
                    )
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
                    shared_retries < max_shared_retries
                    and verify_retries < max_verify_retries
                    and should_retry_for_verification(verification)
                    and not shibei_empty
                ):
                    verify_retries += 1
                    shared_retries += 1
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
                from secretary.agent.tools.edit_text import build_confirm_diff_preview

                desc = tool.describe_action(tool_call.arguments, self._working_dir)
                risk = tool.risk_level
                action_id = f"act_{datetime.now(UTC).strftime('%H%M%S')}_{step_idx}"
                diff_preview = build_confirm_diff_preview(
                    tool_call.name,
                    tool_call.arguments,
                    self._working_dir,
                )
                paired_call = ensure_tool_call_id(tool_call, suffix=str(step_idx))
                pending = PendingConfirmation(
                    action_id=action_id,
                    tool_name=paired_call.name,
                    arguments=paired_call.arguments,
                    description=desc,
                    risk_level=risk,
                    confirmation_kind=confirmation_kind,
                    diff_preview=diff_preview,
                )
                step = StepResult(
                    thought=thought,
                    tool_call=paired_call,
                    tool_output=f"[Waiting for user confirmation] {desc}",
                    needs_confirmation=True,
                )
                steps.append(step)
                # Keep the assistant tool-call turn in the snapshot so resume can
                # pair a real tool result (native) or a [Tool Result] user message.
                if native_used and assistant_message is not None:
                    current_messages.append(
                        assistant_message_for_tool_call(assistant_message, paired_call)
                    )
                else:
                    current_messages.append(
                        {"role": "assistant", "content": raw or thought or desc}
                    )
                return LoopResult(
                    reply=f"我需要你的确认才能继续：\n\n{desc}\n\n是否允许？",
                    steps=steps,
                    used_tools=used_tools,
                    total_steps=step_idx + 1,
                    pending_confirmation=pending,
                    pending_step=step,
                    messages_snapshot=list(current_messages),
                    pause_assistant_message=assistant_message,
                    pause_native_used=native_used,
                )

            # 生命周期钩子：BeforeToolExecution（可修改参数或阻止执行）
            tool_exec_args = tool_call.arguments
            tool_exec_decision = self._run_before_tool_execution_hooks(
                snapshot, tool_call.name, tool_exec_args, self._working_dir,
            )
            if tool_exec_decision.should_skip:
                tool_output = f"[Tool skipped by hook] {tool_exec_decision.reason}"
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
            if tool_exec_decision.modified_arguments is not None:
                tool_exec_args = tool_exec_decision.modified_arguments

            # 协作式取消：在工具执行前再次检查，避免取消后仍执行有副作用的工具。
            if self._is_cancelled():
                return self._cancelled_result(steps, used_tools, step_idx)

            try:
                args_detail = _tool_action_detail(tool, tool_exec_args, self._working_dir)
                combined_detail = _combine_thought_and_args_detail(thought, args_detail)
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
                if hasattr(tool, "bind_cancel_check"):
                    tool.bind_cancel_check(self._cancel_check)
                if self._is_cancelled():
                    return self._cancelled_result(steps, used_tools, step_idx)
                # 全链路可观测性：工具调用计时
                _tool_start = time.perf_counter()
                raw_output = tool.execute(tool_exec_args, self._working_dir)
                _tool_latency_ms = int((time.perf_counter() - _tool_start) * 1000)
                result = _coerce_to_tool_result(raw_output, tool_name=tool_call.name)
                tool_output = result.to_output_string()
                # 外部数据不可信标记：对外部内容工具的返回加定界符
                if result.success:
                    tool_output = _wrap_untrusted(tool_call.name, tool_output)
                tool_output = self._run_after_tool_execution_hooks(
                    snapshot,
                    tool_call.name,
                    tool_exec_args,
                    tool_output,
                    success=result.success,
                )
                used_tools.append(tool_call.name)
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_finished",
                        iteration=iteration,
                        tool_name=tool_call.name,
                        success=True,
                        detail=_progress_detail_preview(tool_output),
                        latency_ms=_tool_latency_ms,
                        paths=tuple(
                            collect_artifact_paths(
                                tool_call.name,
                                tool_exec_args,
                                self._working_dir,
                                output=tool_output,
                                success=True,
                            )
                        ),
                    )
                )
            except Exception as exc:
                error_type, retryable = _classify_tool_error(exc)
                result = ToolResult(
                    error=f"执行 {tool_call.name} 失败: {exc}",
                    error_type=error_type,
                    retryable=retryable,
                )
                tool_output = result.to_output_string()
                logger.warning("Tool %s failed [%s]: %s", tool_call.name, error_type, exc)
                self._emit_progress(
                    ProgressEvent(
                        kind="tool_finished",
                        iteration=iteration,
                        tool_name=tool_call.name,
                        success=False,
                        message=tool_output,
                        detail=_progress_detail_preview(tool_output),
                        error_type=error_type,
                    )
                )

            if len(tool_output) > self._tool_output_limit:
                tool_output = self._truncate_tool_output(tool_output)

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

            from secretary.agent.structured_cards import (
                format_card_reply,
                is_loop_short_circuit_output,
            )

            if is_loop_short_circuit_output(tool_output):
                clarify_reply = format_card_reply(tool_output, thought=thought)
                reply = clarify_reply or thought
                self._emit_progress(
                    ProgressEvent(
                        kind="iteration_completed",
                        iteration=iteration,
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
                    self._llm_config,
                    payload,
                    temperature=temperature,
                    timeout=180.0,
                    thinking="disabled",
                )
                thought = raw.strip()
            except Exception as exc:
                logger.warning("Final summary call failed after max steps: %s", exc)
                thought = (
                    "已用完所有工具轮次，且最终整理回复时出错，"
                    "无法生成完整回答。请基于上方工具结果自行判断，或重新提问。"
                )

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

    def _is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        if self._cancel_check is None:
            return False
        try:
            return bool(self._cancel_check())
        except Exception:
            logger.debug("Cancel check failed", exc_info=True)
            return False

    def _cancelled_result(
        self,
        steps: list[StepResult],
        used_tools: list[str],
        total_steps: int,
    ) -> LoopResult:
        self._emit_progress(
            ProgressEvent(
                kind="stopped",
                iteration=max(1, total_steps + 1),
                message="已取消。",
                success=False,
            )
        )
        self._emit_progress(
            ProgressEvent(kind="final_reply", iteration=max(1, total_steps + 1), message="已取消。")
        )
        return LoopResult(
            reply="已取消。",
            steps=steps,
            used_tools=used_tools,
            total_steps=total_steps,
            cancelled=True,
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
            raw_output = tool.execute(pending.arguments, self._working_dir)
            result = _coerce_to_tool_result(raw_output, tool_name=pending.tool_name)
        except Exception as exc:
            error_type, retryable = _classify_tool_error(exc)
            result = ToolResult.failure(
                f"执行 {pending.tool_name} 失败: {exc}",
                error_type=error_type,
                retryable=retryable,
            )
            logger.warning("Tool %s failed [%s]: %s", pending.tool_name, error_type, exc)

        tool_output = result.to_output_string()
        tool_output = self._truncate_tool_output(tool_output)

        current_messages = list(messages)
        current_messages.append({
            "role": "user",
            "content": f"[User confirmed: {pending.description}]\n[Tool Result: {pending.tool_name}]\n{tool_output}",
        })

        tool_schemas = self._tool_schemas
        payload = self._build_payload(current_messages, tool_schemas)
        raw = chat_completion(
            self._llm_config,
            payload,
            temperature=temperature,
            timeout=180.0,
            thinking=self._resolved_thinking(),
            reasoning_effort=self._reasoning_effort,
        )
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
        # concrete result, so prefer the executed tool output. The unexecuted
        # next_call is exposed via pending_tool_call rather than recorded in
        # steps/used_tools, so callers are not misled into thinking it ran.
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
        logger.info(
            "execute_confirmed: model emitted an unexecuted tool call (%s); "
            "exposing via pending_tool_call",
            next_call.name if next_call else "<none>",
        )
        return LoopResult(
            reply=reply,
            steps=[],
            used_tools=[pending.tool_name],
            total_steps=1,
            pending_confirmation=None,
            pending_tool_call=next_call,
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
            raw_output = tool.execute(pending.arguments, self._working_dir)
            tool_result = _coerce_to_tool_result(raw_output, tool_name=pending.tool_name)
        except Exception as exc:
            error_type, retryable = _classify_tool_error(exc)
            tool_result = ToolResult.failure(
                f"执行 {pending.tool_name} 失败: {exc}",
                error_type=error_type,
                retryable=retryable,
            )
            logger.warning("Tool %s failed [%s]: %s", pending.tool_name, error_type, exc)

        tool_output = tool_result.to_output_string()
        tool_output = self._truncate_tool_output(tool_output)

        continued = list(messages)
        tool_call_id = _pending_tool_call_id(continued, pending.tool_name)
        if tool_call_id:
            # Native tool-calling: close the open tool_call so the model can continue.
            continued.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_output,
                }
            )
        else:
            continued.append(
                {
                    "role": "user",
                    "content": (
                        f"[User confirmed: {pending.description}]\n"
                        f"[Tool Result: {pending.tool_name}]\n{tool_output}"
                    ),
                }
            )
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
        return tool_requires_confirmation(
            tool,
            arguments,
            working_dir=self._working_dir,
            file_auth=self._file_auth,
            require_confirm=self._require_confirm,
        )

    def _run_before_iteration_hooks(self, snapshot: LoopSnapshot) -> StopDecision:
        for hook in self._stop_hooks:
            decision = hook.before_iteration(snapshot)
            if decision.should_stop:
                return decision
        return StopDecision(should_stop=False)

    def _run_before_turn_hooks(
        self, snapshot: LoopSnapshot, messages: list[dict[str, Any]],
    ) -> HookDecision:
        ctx = TurnContext(snapshot=snapshot, messages=tuple(messages))
        for hook in self._before_turn_hooks:
            try:
                decision = hook.before_turn(ctx)
                if decision.should_skip:
                    return decision
            except Exception as exc:
                logger.warning("BeforeTurn hook failed: %s", exc)
        return HookDecision()

    def _run_before_model_call_hooks(
        self,
        snapshot: LoopSnapshot,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        temperature: float,
    ) -> None:
        ctx = ModelCallContext(
            snapshot=snapshot,
            messages=tuple(messages),
            tool_schemas=tuple(tool_schemas),
            temperature=temperature,
        )
        for hook in self._before_model_call_hooks:
            try:
                hook.before_model_call(ctx)
            except Exception as exc:
                logger.warning("BeforeModelCall hook failed: %s", exc)

    def _run_before_tool_execution_hooks(
        self,
        snapshot: LoopSnapshot,
        tool_name: str,
        arguments: dict[str, Any],
        working_dir: Path,
    ) -> HookDecision:
        ctx = ToolExecContext(
            snapshot=snapshot,
            tool_name=tool_name,
            arguments=dict(arguments),
            working_dir=working_dir,
        )
        for hook in self._before_tool_execution_hooks:
            try:
                decision = hook.before_tool_execution(ctx)
                if decision.should_skip:
                    return decision
                if decision.modified_arguments is not None:
                    ctx = ToolExecContext(
                        snapshot=ctx.snapshot,
                        tool_name=ctx.tool_name,
                        arguments=decision.modified_arguments,
                        working_dir=ctx.working_dir,
                    )
            except Exception as exc:
                logger.warning("BeforeToolExecution hook failed: %s", exc)
        return HookDecision(
            modified_arguments=ctx.arguments if ctx.arguments else None
        )

    def _run_after_tool_execution_hooks(
        self,
        snapshot: LoopSnapshot,
        tool_name: str,
        arguments: dict[str, Any],
        tool_output: str,
        *,
        success: bool,
    ) -> str:
        if not self._after_tool_execution_hooks:
            return tool_output
        output = tool_output
        ctx = AfterToolContext(
            snapshot=snapshot,
            tool_name=tool_name,
            arguments=dict(arguments),
            tool_output=output,
            success=success,
            working_dir=self._working_dir,
        )
        for hook in self._after_tool_execution_hooks:
            try:
                decision = hook.after_tool_execution(ctx)
                if decision.modified_output is not None:
                    output = decision.modified_output
                    ctx = AfterToolContext(
                        snapshot=ctx.snapshot,
                        tool_name=ctx.tool_name,
                        arguments=ctx.arguments,
                        tool_output=output,
                        success=ctx.success,
                        working_dir=ctx.working_dir,
                    )
            except Exception as exc:
                logger.warning("AfterToolExecution hook failed: %s", exc)
        return output

    def _sanitize_reply(self, reply: str, snapshot: LoopSnapshot) -> str:
        from secretary.agent.reply_rewriter import prepare_user_facing_reply

        output = prepare_user_facing_reply(
            reply,
            snapshot.latest_user_message,
            self._llm_config,
        )
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
        emit_progress(self._progress_callback, event)

    def _invoke_model(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        *,
        force_read: bool,
        temperature: float,
        on_delta: Callable[[str], None] | None,
        force_content: bool = False,
    ) -> tuple[str, list[ToolCall], dict[str, Any] | None, bool]:
        if self._native_tools_enabled and tool_schemas:
            content_schemas = self._content_tool_schemas(tool_schemas)
            read_schemas = self._read_tool_schemas(tool_schemas)
            if force_content and content_schemas:
                active_schemas = content_schemas
            elif force_read and read_schemas:
                active_schemas = read_schemas
            else:
                active_schemas = tool_schemas
            openai_tools = schemas_to_openai_tools(active_schemas)
            if openai_tools:
                tool_choice: str | dict[str, Any] = (
                    "required" if (force_read or force_content) else "auto"
                )
                try:
                    effort = self._reasoning_effort
                    if force_read or force_content:
                        # Hard grounding / content-force steps: bump to max when possible.
                        if effort in {None, "low", "high"}:
                            effort = "max"
                    result = chat_completion_with_tools(
                        self._llm_config,
                        messages,
                        openai_tools,
                        tool_choice=tool_choice,
                        temperature=temperature,
                        timeout=180.0,
                        thinking=self._resolved_thinking(),
                        reasoning_effort=effort,
                        strict_tools=self._strict_tools,
                    )
                    tool_calls = self._tool_calls_from_result(result)
                    return result.content, tool_calls, result.assistant_message, True
                except Exception as error:
                    # 单步回退：本次 native 调用失败后走文本解析，但不永久禁用，
                    # 后续步骤仍可尝试 native tool calling。
                    # 捕获所有异常（包括 AttributeError/KeyError/json.JSONDecodeError 等
                    # LLM API 返回格式异常响应时可能抛出的错误），确保 native tool
                    # calling 失败时始终回退到文本解析，避免 run() 崩溃。
                    logger.warning("Native tool calling failed this step, falling back to text: %s", error)

        raw = chat_completion(
            self._llm_config,
            messages,
            temperature=temperature,
            timeout=180.0,
            on_delta=on_delta,
            thinking=self._resolved_thinking(),
            reasoning_effort=self._reasoning_effort,
        )
        thought, tool_call = self._parse_response(raw)
        calls = [tool_call] if tool_call is not None else []
        return raw, calls, {"role": "assistant", "content": raw}, False

    def _tool_calls_from_result(self, result: ChatCompletionResult) -> list[ToolCall]:
        if not result.tool_calls:
            return []
        return [
            ToolCall(name=call.name, arguments=call.arguments, id=call.id)
            for call in result.tool_calls
        ]

    def _tool_call_from_result(self, result: ChatCompletionResult) -> ToolCall | None:
        calls = self._tool_calls_from_result(result)
        return calls[0] if calls else None

    def _run_native_tool_batch(
        self,
        tool_calls: list[ToolCall],
        *,
        assistant_message: dict[str, Any] | None,
        thought: str,
        raw: str,
        current_messages: list[dict[str, Any]],
        steps: list[StepResult],
        used_tools: list[str],
        iteration: int,
        step_idx: int,
    ) -> LoopResult | bool | None:
        """Execute a native multi-tool step.

        Returns:
            LoopResult — stop (cancel / pause)
            True — batch ran; continue outer loop
            None — fall back to single-tool handling for tool_calls[0]
        """
        if assistant_message is None:
            return None

        immediate: list[ToolCall] = []
        first_confirm: ToolCall | None = None
        confirm_kind = "action"
        for call in tool_calls:
            tool = self._tools.get(call.name)
            if tool is None:
                immediate.append(call)
                continue
            needs_confirm, kind = self._requires_confirmation(tool, call.arguments)
            if needs_confirm:
                if first_confirm is None:
                    first_confirm = call
                    confirm_kind = kind
            else:
                immediate.append(call)

        if first_confirm is not None and not immediate:
            return None

        if first_confirm is not None and immediate:
            # Mixed batch: run read-only/immediate first, then pause on confirm.
            logger.info(
                "Mixed tool batch (%s immediate, confirming %s); running immediate then pause",
                len(immediate),
                first_confirm.name,
            )

        if not immediate:
            return None

        paired: list[tuple[ToolCall, str]] = []
        for index, call in enumerate(immediate):
            if self._is_cancelled():
                return self._cancelled_result(steps, used_tools, step_idx)
            paired_call = ensure_tool_call_id(call, suffix=f"{step_idx}_{index}")
            tool = self._tools.get(paired_call.name)
            if tool is None:
                output = f"Error: unknown tool '{paired_call.name}'"
            else:
                try:
                    self._emit_progress(
                        ProgressEvent(
                            kind="tool_started",
                            iteration=iteration,
                            tool_name=paired_call.name,
                            detail=_tool_action_detail(
                                tool, paired_call.arguments, self._working_dir
                            ),
                        )
                    )
                    if hasattr(tool, "bind_progress"):
                        tool.bind_progress(self._progress_callback)
                    if hasattr(tool, "bind_cancel_check"):
                        tool.bind_cancel_check(self._cancel_check)
                    output = _coerce_to_tool_result(
                        tool.execute(paired_call.arguments, self._working_dir),
                        tool_name=paired_call.name,
                    ).content
                    used_tools.append(paired_call.name)
                    self._emit_progress(
                        ProgressEvent(
                            kind="tool_finished",
                            iteration=iteration,
                            tool_name=paired_call.name,
                            success=True,
                            detail=_progress_detail_preview(output),
                            paths=tuple(
                                collect_artifact_paths(
                                    paired_call.name,
                                    paired_call.arguments,
                                    self._working_dir,
                                    output=output,
                                    success=True,
                                )
                            ),
                        )
                    )
                except Exception as exc:
                    output = f"Error executing {paired_call.name}: {exc}"
                    logger.warning("Tool %s failed: %s", paired_call.name, exc)
                    self._emit_progress(
                        ProgressEvent(
                            kind="tool_finished",
                            iteration=iteration,
                            tool_name=paired_call.name,
                            success=False,
                            message=output,
                            detail=_progress_detail_preview(output),
                        )
                    )
            if len(output) > self._tool_output_limit:
                output = self._truncate_tool_output(output)
            steps.append(
                StepResult(thought=thought if index == 0 else "", tool_call=paired_call, tool_output=output)
            )
            paired.append((paired_call, output))

        # Rebuild assistant tool_calls to match executed ids (and optional confirm).
        batch_calls = [call for call, _ in paired]
        if first_confirm is not None:
            confirm_paired = ensure_tool_call_id(first_confirm, suffix=f"{step_idx}_confirm")
            batch_calls.append(confirm_paired)
        batch_assistant = assistant_message_for_batch(assistant_message, batch_calls)
        current_messages.append(batch_assistant)
        for call, output in paired:
            current_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                }
            )

        if first_confirm is not None:
            from secretary.agent.tools.edit_text import build_confirm_diff_preview

            confirm_paired = batch_calls[-1]
            tool = self._tools.get(confirm_paired.name)
            desc = (
                tool.describe_action(confirm_paired.arguments, self._working_dir)
                if tool is not None
                else confirm_paired.name
            )
            risk = tool.risk_level if tool is not None else "high"
            pending = PendingConfirmation(
                action_id=f"act_{datetime.now(UTC).strftime('%H%M%S')}_{step_idx}",
                tool_name=confirm_paired.name,
                arguments=confirm_paired.arguments,
                description=desc,
                risk_level=risk,
                confirmation_kind=confirm_kind,
                diff_preview=build_confirm_diff_preview(
                    confirm_paired.name,
                    confirm_paired.arguments,
                    self._working_dir,
                ),
            )
            step = StepResult(
                thought=thought,
                tool_call=confirm_paired,
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
                pause_assistant_message=batch_assistant,
                pause_native_used=True,
            )

        return True

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

    def _content_tool_schemas(
        self, tool_schemas: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Schemas that open file body — used when force_content=True."""
        from secretary.agent.grounding import is_content_read_tool

        return [
            schema
            for schema in tool_schemas
            if is_content_read_tool(str(schema.get("name") or ""))
        ]

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        tool_schemas: list[dict[str, Any]],
        *,
        native: bool = False,
    ) -> list[dict[str, str]]:
        instruction = self._build_instruction(tool_schemas, native=native)
        return build_payload(messages, instruction)

    def _build_instruction(
        self,
        tool_schemas: list[dict[str, Any]],
        *,
        native: bool,
    ) -> str:
        """Build (and cache) the system instruction embedding tool schemas."""
        base = build_cached_instruction(
            tool_schemas,
            native=native,
            tool_names=self._tool_names,
            cache=self._instruction_cache,
        )
        cwd = self._working_dir
        return (
            f"{base}\n\n"
            f"Working directory (cwd): {cwd}\n"
            "Relative tool paths resolve against this cwd. "
            "When exploring the active project, start with list_dir on `.` or this path."
        )

    def _parse_response(self, raw: str) -> tuple[str, ToolCall | None]:
        return parse_tool_call_response(raw)

    def _truncate_tool_output(self, text: str) -> str:
        if len(text) > self._tool_output_limit:
            return truncate_chars(text, self._tool_output_limit)
        return text

    def _run_injected_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        iteration: int,
        step_idx: int,
        call_id: str,
        thought: str,
        steps: list[StepResult],
        used_tools: list[str],
    ) -> LoopResult | tuple[ToolCall, str]:
        """Execute an auto-injected tool (list_dir preflight / retry / forced web).

        Emits tool_started/tool_finished progress events and records the
        StepResult. Returns a LoopResult when the turn must stop (cancelled),
        or the (call, output) pair for the caller to append to history.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            logger.warning("Injected tool '%s' not available", tool_name)
            call = ToolCall(name=tool_name, arguments=arguments, id=call_id)
            return call, f"Error: unknown tool '{tool_name}'"
        if self._is_cancelled():
            return self._cancelled_result(steps, used_tools, step_idx)

        _start = time.perf_counter()
        try:
            output = _coerce_to_tool_result(
                tool.execute(arguments, self._working_dir),
                tool_name=tool_name,
            ).to_output_string()
        except Exception as exc:
            error_type, retryable = _classify_tool_error(exc)
            output = ToolResult.failure(
                f"Error: {exc}",
                error_type=error_type,
                retryable=retryable,
            ).to_output_string()
        latency_ms = int((time.perf_counter() - _start) * 1000)

        call = ToolCall(name=tool_name, arguments=arguments, id=call_id)
        steps.append(StepResult(thought=thought, tool_call=call, tool_output=output))
        used_tools.append(tool_name)
        self._emit_progress(
            ProgressEvent(
                kind="tool_started",
                iteration=iteration,
                tool_name=tool_name,
                detail=_tool_action_detail(tool, arguments, self._working_dir),
            )
        )
        self._emit_progress(
            ProgressEvent(
                kind="tool_finished",
                iteration=iteration,
                tool_name=tool_name,
                success=not str(output).startswith("Error:"),
                latency_ms=latency_ms,
            )
        )
        return call, output


def _index_tools(tools: list[Tool]) -> dict[str, Tool]:
    """Index tools by name and map Pi↔legacy aliases for lookup."""
    indexed = {tool.name: tool for tool in tools}
    for legacy, canonical in (
        ("file_read", "read"),
        ("file_write", "write"),
        ("patch", "edit"),
        ("list_dir", "ls"),
        ("search_files", "grep"),
        ("glob_files", "glob"),
        ("find", "glob"),
    ):
        if canonical in indexed and legacy not in indexed:
            indexed[legacy] = indexed[canonical]
        if legacy in indexed and canonical not in indexed:
            indexed[canonical] = indexed[legacy]
    return indexed


def _default_tools() -> list[Tool]:
    from secretary.agent.p0_tools import EditTool
    from secretary.agent.tools.fs import MoveTool
    from secretary.agent.web_search import WebSearchTool

    return [
        ListDirTool(),
        FileReadTool(),
        FileWriteTool(),
        EditTool(),
        MoveTool(),
        FileDeleteTool(),
        ShellTool(),
        WebFetchTool(),
        WebSearchTool(),
    ]


