"""Turn-scoped runner that constructs AgentLoop / aisuite runtime and emits turn_* events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from secretary.agent.harness_config import ConfirmRequireConfig
from secretary.agent.lifecycle_hooks import (
    AfterToolExecutionHook,
    BeforeModelCallHook,
    BeforeToolExecutionHook,
    BeforeTurnHook,
)
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, LoopResult
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.session_store import SessionStore
from secretary.agent.tools.base import Tool
from secretary.agent.turn_models import TurnContext
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)

RuntimeBackend = Literal["legacy", "aisuite", "agents_sdk"]


def _uses_legacy_pause(pending: Any) -> bool:
    """A pending raised by a non-SDK backend (or a legacy restore) has no sdk_state."""
    return not str(getattr(pending, "sdk_state", "") or "")


def _find_spawn_deps(tools: list[Tool]) -> Any | None:
    """Extract SubAgentDeps from the SpawnSubagentTool in a tool set, if any."""
    for tool in tools:
        if getattr(tool, "name", "") == "spawn_subagent":
            return getattr(tool, "deps", None)
    return None


@dataclass(frozen=True)
class AgentTurnPlan:
    """Prepared inputs for one agent loop turn."""

    messages: list[dict[str, str]]
    max_steps: int
    tools: list[Tool]
    force_web_first_step: bool = False
    # True when the user explicitly selected a workspace folder this turn
    # (chat request carried a non-empty working_dir). Triggers an unconditional
    # top-level list_dir preflight at step 0 so the model starts with real
    # entry names instead of hallucinating paths.
    explicit_working_dir: bool = False
    compaction_max_tokens: int | None = None
    compaction_keep_tail: int | None = None
    thinking: str = "enabled"
    reasoning_effort: str | None = "high"
    strict_tools: bool = False
    runtime_backend: RuntimeBackend = "aisuite"
    require_confirm: ConfirmRequireConfig | None = None
    full_fs_access: bool = False
    max_tool_output_chars: int | None = None


@dataclass
class LoopHookBundle:
    """Optional lifecycle hooks passed into each AgentLoop."""

    before_turn: list[BeforeTurnHook] = field(default_factory=list)
    before_model_call: list[BeforeModelCallHook] = field(default_factory=list)
    before_tool_execution: list[BeforeToolExecutionHook] = field(default_factory=list)
    after_tool_execution: list[AfterToolExecutionHook] = field(default_factory=list)


def enrich_progress_event(event: ProgressEvent, turn: TurnContext | None) -> ProgressEvent:
    if turn is None:
        return event
    return replace(
        event,
        turn_id=turn.turn_id,
        thread_id=turn.thread_id,
        item_id=turn.next_item_id(),
        parent_turn_id=turn.parent_turn_id or event.parent_turn_id,
    )


def bind_turn_progress(
    callback: Callable[[ProgressEvent], None] | None,
    turn: TurnContext | None,
) -> Callable[[ProgressEvent], None] | None:
    if callback is None:
        return None

    def wrapped(event: ProgressEvent) -> None:
        callback(enrich_progress_event(event, turn))

    return wrapped


def _prefer_legacy_loop(plan: AgentTurnPlan) -> bool:
    """Features not yet ported to aisuite/SDK Runners keep the Lumina AgentLoop.

    Completions still go through vendored aisuite via ``llm_client`` (legacy path).
    """
    if plan.runtime_backend == "legacy":
        return True
    if plan.force_web_first_step:
        return True
    if plan.runtime_backend == "agents_sdk":
        # Sub-agent delegation is handled natively (per-archetype as_tools).
        return False
    # aisuite backend: strict_tools unsupported and spawn falls back to legacy.
    if plan.strict_tools:
        logger.info("strict_tools=True not supported on aisuite Runner; using legacy AgentLoop")
        return True
    tool_names = {getattr(tool, "name", "") for tool in plan.tools}
    if "spawn_subagent" in tool_names:
        return True
    return False


class TurnRunner:
    """Runs agent loops inside a Turn lifecycle with turn_* progress events."""

    def __init__(
        self,
        file_auth: FileAuthService,
        *,
        hooks: LoopHookBundle | None = None,
        hooks_factory: Callable[[list[Tool]], LoopHookBundle] | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self._file_auth = file_auth
        self._hooks = hooks
        self._hooks_factory = hooks_factory
        self._session_store = session_store or SessionStore()

    @property
    def session_store(self) -> SessionStore:
        return self._session_store

    def _resolve_hooks(self, tools: list[Tool]) -> LoopHookBundle:
        if self._hooks_factory is not None:
            return self._hooks_factory(tools)
        return self._hooks or LoopHookBundle()

    def _build_agent_loop(
        self,
        llm_config: LlmConfig,
        *,
        tools: list[Tool],
        max_steps: int,
        working_dir: Path | None,
        progress_callback: Callable[[ProgressEvent], None] | None,
        on_subagent_paused: Callable[[Any], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        force_web_first_step: bool = False,
        explicit_working_dir: bool = False,
        compaction_max_tokens: int | None = None,
        compaction_keep_tail: int | None = None,
        thinking: str = "enabled",
        reasoning_effort: str | None = "high",
        strict_tools: bool = False,
        require_confirm: ConfirmRequireConfig | None = None,
        max_tool_output_chars: int | None = None,
    ) -> AgentLoop:
        hooks = self._resolve_hooks(tools)
        return AgentLoop(
            llm_config,
            tools=tools,
            max_steps=max_steps,
            file_auth=self._file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
            on_subagent_paused=on_subagent_paused,
            cancel_check=cancel_check,
            before_turn_hooks=hooks.before_turn,
            before_model_call_hooks=hooks.before_model_call,
            before_tool_execution_hooks=hooks.before_tool_execution,
            after_tool_execution_hooks=hooks.after_tool_execution,
            force_web_first_step=force_web_first_step,
            explicit_working_dir=explicit_working_dir,
            compaction_max_tokens=compaction_max_tokens,
            compaction_keep_tail=compaction_keep_tail,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            strict_tools=strict_tools,
            require_confirm=require_confirm,
            max_tool_output_chars=max_tool_output_chars,
        )

    def run_agent_turn(
        self,
        llm_config: LlmConfig,
        plan: AgentTurnPlan,
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        on_subagent_paused: Callable[[Any], None] | None = None,
        turn: TurnContext | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> LoopResult:
        wrapped = bind_turn_progress(progress_callback, turn)
        if wrapped is not None and turn is not None:
            wrapped(
                ProgressEvent(
                    kind="turn_started",
                    iteration=0,
                    message=turn.user_message[:200],
                    turn_id=turn.turn_id,
                    thread_id=turn.thread_id,
                )
            )
        try:
            from secretary.agent.fs_jail import full_fs_access_scope

            with full_fs_access_scope(plan.full_fs_access):
                cwd = working_dir or Path.home()
                if plan.runtime_backend == "agents_sdk":
                    from secretary.agent.agents_sdk_runtime import run_with_agents_sdk

                    result = run_with_agents_sdk(
                        llm_config=llm_config,
                        messages=list(plan.messages),
                        tools=plan.tools,
                        working_dir=cwd,
                        max_turns=plan.max_steps,
                        temperature=temperature,
                        thinking=plan.thinking,
                        reasoning_effort=plan.reasoning_effort,
                        strict_tools=plan.strict_tools,
                        file_auth=self._file_auth,
                        progress_callback=wrapped,
                        cancel_check=cancel_check,
                        explicit_working_dir=plan.explicit_working_dir,
                        require_confirm=plan.require_confirm,
                        compaction_max_tokens=plan.compaction_max_tokens,
                        compaction_keep_tail=plan.compaction_keep_tail,
                        subagent_deps=_find_spawn_deps(plan.tools),
                    )
                elif plan.runtime_backend == "aisuite" and not _prefer_legacy_loop(plan):
                    from secretary.agent.aisuite_runtime import run_with_aisuite

                    result = run_with_aisuite(
                        llm_config=llm_config,
                        messages=list(plan.messages),
                        tools=plan.tools,
                        working_dir=cwd,
                        max_turns=plan.max_steps,
                        temperature=temperature,
                        thinking=plan.thinking,
                        reasoning_effort=plan.reasoning_effort,
                        file_auth=self._file_auth,
                        progress_callback=wrapped,
                        cancel_check=cancel_check,
                        on_subagent_paused=on_subagent_paused,
                        explicit_working_dir=plan.explicit_working_dir,
                        require_confirm=plan.require_confirm,
                        compaction_max_tokens=plan.compaction_max_tokens,
                        compaction_keep_tail=plan.compaction_keep_tail,
                    )
                else:
                    loop = self._build_agent_loop(
                        llm_config,
                        tools=plan.tools,
                        max_steps=plan.max_steps,
                        working_dir=working_dir,
                        progress_callback=wrapped,
                        on_subagent_paused=on_subagent_paused,
                        cancel_check=cancel_check,
                        force_web_first_step=plan.force_web_first_step,
                        explicit_working_dir=plan.explicit_working_dir,
                        compaction_max_tokens=plan.compaction_max_tokens,
                        compaction_keep_tail=plan.compaction_keep_tail,
                        thinking=plan.thinking,
                        reasoning_effort=plan.reasoning_effort,
                        strict_tools=plan.strict_tools,
                        require_confirm=plan.require_confirm,
                        max_tool_output_chars=plan.max_tool_output_chars,
                    )
                    result = loop.run(plan.messages, temperature=temperature)
            if wrapped is not None and turn is not None:
                if result.pending_confirmation:
                    wrapped(
                        ProgressEvent(
                            kind="pause_confirmation",
                            iteration=result.total_steps,
                            message=result.pending_confirmation.description,
                            tool_name=result.pending_confirmation.tool_name,
                            turn_id=turn.turn_id,
                            thread_id=turn.thread_id,
                            success=False,
                        )
                    )
                    turn.status = "paused"
                wrapped(
                    ProgressEvent(
                        kind="turn_completed",
                        iteration=result.total_steps,
                        message=result.reply[:200],
                        turn_id=turn.turn_id,
                        thread_id=turn.thread_id,
                        success=result.pending_confirmation is None,
                    )
                )
                if turn.status != "paused":
                    turn.status = "completed"
            return result
        except Exception:
            if turn is not None:
                turn.status = "failed"
            raise

    def run_confirmed_action(
        self,
        llm_config: LlmConfig,
        tools: list[Tool],
        pending: Any,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        turn: TurnContext | None = None,
        cancel_check: Callable[[], bool] | None = None,
        runtime_backend: RuntimeBackend = "aisuite",
        max_steps: int = 20,
        thinking: str = "enabled",
        reasoning_effort: str | None = "high",
        full_fs_access: bool = False,
        strict_tools: bool = False,
        compaction_max_tokens: int | None = None,
        compaction_keep_tail: int | None = None,
        max_tool_output_chars: int | None = None,
    ) -> LoopResult:
        wrapped = bind_turn_progress(progress_callback, turn)
        cwd = working_dir or Path.home()
        tool_names = {getattr(tool, "name", "") for tool in tools}
        use_aisuite = (
            runtime_backend == "aisuite"
            and "spawn_subagent" not in tool_names
            and not strict_tools
        )
        from secretary.agent.fs_jail import full_fs_access_scope

        with full_fs_access_scope(full_fs_access):
            if runtime_backend == "agents_sdk" and not _uses_legacy_pause(pending):
                from secretary.agent.agents_sdk_runtime import resume_with_agents_sdk

                return resume_with_agents_sdk(
                    llm_config=llm_config,
                    pending=pending,
                    messages=list(messages),
                    tools=tools,
                    working_dir=cwd,
                    max_turns=max_steps,
                    temperature=temperature,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort,
                    strict_tools=strict_tools,
                    file_auth=self._file_auth,
                    progress_callback=wrapped,
                    cancel_check=cancel_check,
                    subagent_deps=_find_spawn_deps(tools),
                )
            if use_aisuite:
                from secretary.agent.aisuite_runtime import resume_with_aisuite

                return resume_with_aisuite(
                    llm_config=llm_config,
                    pending=pending,
                    messages=list(messages),
                    tools=tools,
                    working_dir=cwd,
                    max_turns=max_steps,
                    temperature=temperature,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort,
                    file_auth=self._file_auth,
                    progress_callback=wrapped,
                    cancel_check=cancel_check,
                    compaction_max_tokens=compaction_max_tokens,
                    compaction_keep_tail=compaction_keep_tail,
                )
            loop = self._build_agent_loop(
                llm_config,
                tools=tools,
                max_steps=max_steps,
                working_dir=working_dir,
                progress_callback=wrapped,
                cancel_check=cancel_check,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                strict_tools=strict_tools,
                max_tool_output_chars=max_tool_output_chars,
            )
            return loop.resume_after_confirmation(pending, messages, temperature=temperature)

    def resume_after_subagent(
        self,
        llm_config: LlmConfig,
        resume: Any,
        tool_output: str,
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        on_subagent_paused: Callable[[Any], None] | None = None,
        turn: TurnContext | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> LoopResult:
        wrapped = bind_turn_progress(progress_callback, turn)
        from secretary.agent.subagent.resume import ParentTurnResumeState

        if not isinstance(resume, ParentTurnResumeState):
            return LoopResult(
                reply=str(tool_output),
                steps=[],
                used_tools=["spawn_subagent"],
                total_steps=1,
            )
        step = resume.pending_step
        if step.tool_call is None:
            return LoopResult(
                reply=str(tool_output),
                steps=[],
                used_tools=["spawn_subagent"],
                total_steps=1,
            )
        loop = self._build_agent_loop(
            llm_config,
            tools=list(resume.tools),
            max_steps=resume.max_steps,
            working_dir=working_dir,
            progress_callback=wrapped,
            on_subagent_paused=on_subagent_paused,
            cancel_check=cancel_check,
        )
        return loop.resume_after_subagent_tool(
            resume.messages_snapshot,
            thought=step.thought,
            tool_call=step.tool_call,
            tool_output=tool_output,
            assistant_message=resume.assistant_message,
            native_used=resume.native_used,
            step_idx=resume.step_idx,
            temperature=temperature,
        )
