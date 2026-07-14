"""Execution orchestrator for agent tool loops."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secretary.agent.lifecycle_hooks import (
    AfterToolExecutionHook,
    BeforeModelCallHook,
    BeforeToolExecutionHook,
    BeforeTurnHook,
)
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, LoopResult
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.tools.base import Tool
from secretary.services.file_auth import FileAuthService


@dataclass(frozen=True)
class AgentTurnPlan:
    """Prepared inputs for one agent loop turn."""

    messages: list[dict[str, str]]
    max_steps: int
    tools: list[Tool]


@dataclass
class LoopHookBundle:
    """Optional lifecycle hooks passed into each AgentLoop."""

    before_turn: list[BeforeTurnHook] = field(default_factory=list)
    before_model_call: list[BeforeModelCallHook] = field(default_factory=list)
    before_tool_execution: list[BeforeToolExecutionHook] = field(default_factory=list)
    after_tool_execution: list[AfterToolExecutionHook] = field(default_factory=list)


class TurnOrchestrator:
    """Thin orchestration layer around AgentLoop execution."""

    def __init__(
        self,
        file_auth: FileAuthService,
        *,
        hooks: LoopHookBundle | None = None,
        hooks_factory: Callable[[list[Tool]], LoopHookBundle] | None = None,
    ) -> None:
        self._file_auth = file_auth
        self._hooks = hooks
        self._hooks_factory = hooks_factory

    def _resolve_hooks(self, tools: list[Tool]) -> LoopHookBundle:
        if self._hooks_factory is not None:
            return self._hooks_factory(tools)
        return self._hooks or LoopHookBundle()

    def run_agent_turn(
        self,
        llm_config: LlmConfig,
        plan: AgentTurnPlan,
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        on_subagent_paused: Callable[[Any], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> LoopResult:
        hooks = self._resolve_hooks(plan.tools)
        loop = AgentLoop(
            llm_config,
            tools=plan.tools,
            max_steps=plan.max_steps,
            file_auth=self._file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
            on_subagent_paused=on_subagent_paused,
            cancel_check=cancel_check,
            before_turn_hooks=hooks.before_turn,
            before_model_call_hooks=hooks.before_model_call,
            before_tool_execution_hooks=hooks.before_tool_execution,
            after_tool_execution_hooks=hooks.after_tool_execution,
        )
        return loop.run(plan.messages, temperature=temperature)

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
        cancel_check: Callable[[], bool] | None = None,
    ) -> LoopResult:
        hooks = self._resolve_hooks(tools)
        loop = AgentLoop(
            llm_config,
            tools=tools,
            max_steps=20,
            file_auth=self._file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
            cancel_check=cancel_check,
            before_turn_hooks=hooks.before_turn,
            before_model_call_hooks=hooks.before_model_call,
            before_tool_execution_hooks=hooks.before_tool_execution,
            after_tool_execution_hooks=hooks.after_tool_execution,
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
        cancel_check: Callable[[], bool] | None = None,
    ) -> LoopResult:
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
        hooks = self._resolve_hooks(list(resume.tools))
        loop = AgentLoop(
            llm_config,
            tools=resume.tools,
            max_steps=resume.max_steps,
            file_auth=self._file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
            on_subagent_paused=on_subagent_paused,
            cancel_check=cancel_check,
            before_turn_hooks=hooks.before_turn,
            before_model_call_hooks=hooks.before_model_call,
            before_tool_execution_hooks=hooks.before_tool_execution,
            after_tool_execution_hooks=hooks.after_tool_execution,
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
