"""Run isolated child AgentLoop instances for delegated tasks."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from secretary.agent.delegation import DelegationResult
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, LoopResult
from secretary.agent.progress_events import ProgressEvent, _archetype_display_name
from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.policy import (
    MAX_PARALLEL_EXPLORE,
    MAX_SPAWN_DEPTH,
    MAX_SPAWNS_PER_TURN,
    SUBAGENT_TIMEOUT_SEC,
)
from secretary.agent.subagent.registry import (
    ArchetypeSpec,
    build_messages,
    get_archetype,
    list_archetype_names,
    resolve_tools,
)
from secretary.agent.subagent.resume import SubAgentResumeState
from secretary.agent.subagent.summarize import format_subagent_result
from secretary.memory.db import MemoryStore
from secretary.memory.lumina_memory import LuminaMemory
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubAgentDeps:
    llm_config: LlmConfig
    file_auth: FileAuthService | None
    memory_store: MemoryStore
    memory: LuminaMemory
    lumina_dir: Path | None = None
    temperature: float = 0.3


class SubAgentRunner:
    def __init__(
        self,
        deps: SubAgentDeps,
        *,
        on_paused: Callable[[SubAgentResumeState], None] | None = None,
    ) -> None:
        self._deps = deps
        self._on_paused = on_paused

    def run_from_tool(
        self,
        arguments: dict[str, Any],
        spawn_context: SpawnContext,
        working_dir: Path,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> str:
        context = str(arguments.get("context", "")).strip()
        archetype = str(arguments.get("archetype", "explore")).strip().lower() or "explore"
        parallel_goals = _parse_parallel_goals(arguments.get("goals"))
        goal = str(arguments.get("goal", "")).strip()
        success_criteria = str(arguments.get("success_criteria", "")).strip()
        if parallel_goals:
            if archetype != "explore":
                return "Error: parallel goals are only supported for archetype 'explore'."
            return self._run_parallel_explore(
                parallel_goals,
                context=context,
                spawn_context=spawn_context,
                working_dir=working_dir,
                progress_callback=progress_callback,
                success_criteria=success_criteria,
            )
        if not goal:
            return "Error: spawn_subagent requires a non-empty goal."

        if archetype == "verify" and not success_criteria:
            return "Error: verify archetype requires machine-verifiable success_criteria"

        spec = get_archetype(archetype, self._deps.lumina_dir)
        policy_error = self._check_policy(spawn_context, spec)
        if policy_error:
            return policy_error

        if spec is None:
            supported = ", ".join(list_archetype_names(self._deps.lumina_dir))
            return f"Error: unknown or unsupported archetype '{archetype}'. Supported: {supported}."

        run_id = uuid.uuid4().hex[:12]
        child_session_id = spawn_context.child_session_id(run_id)
        # Intentionally counts even on failure: prevents retry storms from
        # repeatedly spawning sub-agents that exhaust the turn quota.
        spawn_context.record_spawn()

        self._emit(
            progress_callback,
            ProgressEvent(
                kind="subagent_started",
                iteration=0,
                message=f"正在派生子 Agent（{_archetype_display_name(archetype)}）：{goal[:100]}",
                sub_run_id=run_id,
                archetype=archetype,
                goal=goal[:200],
                subagent_status="running",
            ),
        )

        tools = resolve_tools(archetype, self._deps)
        messages = build_messages(
            goal=goal, context=context, spec=spec,
            success_criteria=success_criteria,
        )
        wrapped_progress = self._wrap_progress(progress_callback, run_id, archetype)
        child_context = spawn_context.child_context()

        try:
            self._deps.memory.create_session(child_session_id)
            self._deps.memory.add_message(child_session_id, "user", goal[:MAX_MESSAGE_LEN])
            summary = self._run_child_loop(
                messages=messages,
                tools=tools,
                max_steps=spec.max_steps,
                working_dir=working_dir,
                progress_callback=wrapped_progress,
                run_id=run_id,
                archetype=archetype,
                goal=goal,
                context=context,
                success_criteria=success_criteria,
                child_session_id=child_session_id,
                spawn_context=child_context,
            )
            if isinstance(summary, SubAgentResumeState):
                self._deps.memory.end_session(
                    child_session_id, summary="paused: awaiting confirmation"
                )
                return DelegationResult(
                    kind="subagent",
                    run_id=summary.run_id,
                    provider=summary.archetype,
                    goal=goal,
                    summary=f"子 Agent ({summary.archetype}) 已暂停，等待确认",
                    success=False,
                    status="paused",
                    detail=summary.pending.description,
                ).to_tool_output()

            self._deps.memory.add_message(child_session_id, "assistant", summary[:MAX_MESSAGE_LEN])
            self._deps.memory.end_session(child_session_id, summary=summary[:200])
        except Exception as exc:
            logger.warning("Sub-agent run failed: %s", exc)
            try:
                self._deps.memory.end_session(child_session_id, summary=f"failed: {exc}"[:200])
            except Exception:
                logger.debug("Failed to end session %s", child_session_id)
            summary = f"Error: sub-agent failed: {exc}"
            success = False
        else:
            success = not str(summary).startswith("Error:")

        self._emit(
            progress_callback,
            ProgressEvent(
                kind="subagent_finished",
                iteration=0,
                message=str(summary)[:200],
                sub_run_id=run_id,
                archetype=archetype,
                goal=goal[:200],
                subagent_status="done" if success else "failed",
                success=success,
            ),
        )
        return str(summary)

    def resume_paused(
        self,
        state: SubAgentResumeState,
        working_dir: Path,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> str:
        """Continue a paused sub-agent after user confirmed a risky tool."""
        tools = resolve_tools(state.archetype, self._deps)
        wrapped = self._wrap_progress(progress_callback, state.run_id, state.archetype)
        loop = AgentLoop(
            state.llm_config,
            tools=tools,
            max_steps=state.max_steps,
            file_auth=self._deps.file_auth,
            progress_callback=wrapped,
            working_dir=working_dir,
        )

        def _execute() -> LoopResult:
            return loop.resume_after_confirmation(
                state.pending,
                state.messages,
                temperature=state.temperature,
            )

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_execute)
        try:
            try:
                result = future.result(timeout=SUBAGENT_TIMEOUT_SEC)
            except FuturesTimeoutError:
                loop.cancel()
                try:
                    result = future.result(timeout=2.0)
                except FuturesTimeoutError:
                    result = LoopResult(
                        reply=f"子 agent 恢复超时（>{SUBAGENT_TIMEOUT_SEC}s）且未响应取消。",
                        steps=[],
                        used_tools=[],
                        total_steps=0,
                    )
                logger.warning(
                    "Sub-agent %s resume timed out after %ss",
                    state.run_id,
                    SUBAGENT_TIMEOUT_SEC,
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        try:
            if result.pending_confirmation and result.messages_snapshot is not None:
                paused = SubAgentResumeState(
                    run_id=state.run_id,
                    archetype=state.archetype,
                    goal=state.goal,
                    context=state.context,
                    success_criteria=state.success_criteria,
                    child_session_id=state.child_session_id,
                    parent_session_id=state.parent_session_id,
                    messages=result.messages_snapshot,
                    max_steps=state.max_steps,
                    working_dir=working_dir,
                    pending=result.pending_confirmation,
                    llm_config=state.llm_config,
                    temperature=state.temperature,
                    pending_step=result.pending_step,
                    steps_completed=result.total_steps,
                    used_tools=list(result.used_tools),
                )
                if self._on_paused is not None:
                    self._on_paused(paused)
                self._emit(
                    progress_callback,
                    ProgressEvent(
                        kind="subagent_paused",
                        iteration=0,
                        message=paused.pending.description,
                        sub_run_id=state.run_id,
                        archetype=state.archetype,
                        goal=state.goal[:200],
                        subagent_status="paused",
                    ),
                )
                return f"子 Agent ({state.archetype}) 仍需确认：{paused.pending.description}"

            summary = format_subagent_result(
                result,
                run_id=state.run_id,
                archetype=state.archetype,
                goal=state.goal,
            )
            self._deps.memory.add_message(state.child_session_id, "assistant", summary[:MAX_MESSAGE_LEN])
            self._deps.memory.end_session(state.child_session_id, summary=summary[:200])
            self._emit(
                progress_callback,
                ProgressEvent(
                    kind="subagent_finished",
                    iteration=0,
                    message=summary[:200],
                    sub_run_id=state.run_id,
                    archetype=state.archetype,
                    goal=state.goal[:200],
                    subagent_status="done",
                    success=True,
                ),
            )
            return summary
        except Exception as exc:
            logger.warning("Sub-agent resume failed: %s", exc)
            try:
                self._deps.memory.end_session(
                    state.child_session_id, summary=f"failed: {exc}"[:200]
                )
            except Exception:
                logger.debug("Failed to end session %s", state.child_session_id)
            self._emit(
                progress_callback,
                ProgressEvent(
                    kind="subagent_finished",
                    iteration=0,
                    message=str(exc)[:200],
                    sub_run_id=state.run_id,
                    archetype=state.archetype,
                    goal=state.goal[:200],
                    subagent_status="failed",
                    success=False,
                ),
            )
            return f"Error: sub-agent resume failed: {exc}"

    def _run_child_loop(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[Any],
        max_steps: int,
        working_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None,
        run_id: str,
        archetype: str,
        goal: str = "",
        context: str = "",
        success_criteria: str = "",
        child_session_id: str = "",
        spawn_context: SpawnContext | None = None,
    ) -> str | SubAgentResumeState:
        loop = AgentLoop(
            self._deps.llm_config,
            tools=tools,
            max_steps=max_steps,
            file_auth=self._deps.file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
        )

        def _execute() -> LoopResult | SubAgentResumeState:
            result = loop.run(messages, temperature=self._deps.temperature)
            if result.pending_confirmation and result.messages_snapshot is not None:
                paused = SubAgentResumeState(
                    run_id=run_id,
                    archetype=archetype,
                    goal=goal,
                    context=context,
                    success_criteria=success_criteria,
                    child_session_id=child_session_id,
                    parent_session_id=spawn_context.parent_session_id if spawn_context else "",
                    messages=result.messages_snapshot,
                    max_steps=max_steps,
                    working_dir=working_dir,
                    pending=result.pending_confirmation,
                    llm_config=self._deps.llm_config,
                    temperature=self._deps.temperature,
                    pending_step=result.pending_step,
                    steps_completed=result.total_steps,
                    used_tools=list(result.used_tools),
                )
                if self._on_paused is not None:
                    self._on_paused(paused)
                self._emit(
                    progress_callback,
                    ProgressEvent(
                        kind="subagent_paused",
                        iteration=0,
                        message=paused.pending.description,
                        sub_run_id=run_id,
                        archetype=archetype,
                        goal=goal,
                        subagent_status="paused",
                    ),
                )
                return paused
            return result

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_execute)
        try:
            try:
                outcome = future.result(timeout=SUBAGENT_TIMEOUT_SEC)
            except FuturesTimeoutError:
                # 协作式取消：设置取消标志，子 loop 在下一轮迭代退出。
                # future.cancel() 对正在运行的任务无效，靠 _cancelled 标志协作终止。
                loop.cancel()
                try:
                    # 缩短宽限期，避免主线程被 LLM 调用无限阻塞
                    outcome = future.result(timeout=2.0)
                except FuturesTimeoutError:
                    outcome = LoopResult(
                        reply=f"子 agent 超时（>{SUBAGENT_TIMEOUT_SEC}s）且未响应取消。",
                        steps=[],
                        used_tools=[],
                        total_steps=0,
                    )
                logger.warning("Sub-agent %s timed out after %ss", run_id, SUBAGENT_TIMEOUT_SEC)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        if isinstance(outcome, SubAgentResumeState):
            return outcome
        return format_subagent_result(outcome, run_id=run_id, archetype=archetype, goal=goal)

    def _check_policy(
        self, spawn_context: SpawnContext, spec: ArchetypeSpec | None
    ) -> str | None:
        if spawn_context.depth >= MAX_SPAWN_DEPTH:
            return (
                f"Error: spawn depth limit reached ({MAX_SPAWN_DEPTH}). "
                "Sub-agents cannot spawn further sub-agents."
            )
        if spawn_context.get_spawns_this_turn() >= MAX_SPAWNS_PER_TURN:
            return (
                f"Error: spawn quota exceeded ({MAX_SPAWNS_PER_TURN} per turn). "
                "Finish current sub-tasks before delegating more."
            )
        if spec is None:
            return "Error: unknown archetype."
        return None

    def _run_parallel_explore(
        self,
        goals: list[str],
        *,
        context: str,
        spawn_context: SpawnContext,
        working_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None,
        success_criteria: str = "",
    ) -> str:
        if spawn_context.depth >= MAX_SPAWN_DEPTH:
            return f"Error: spawn depth limit reached ({MAX_SPAWN_DEPTH})."
        remaining = MAX_SPAWNS_PER_TURN - spawn_context.get_spawns_this_turn()
        if remaining < len(goals):
            return (
                f"Error: spawn quota exceeded; need {len(goals)} slots, "
                f"{remaining} remaining ({MAX_SPAWNS_PER_TURN} per turn)."
            )

        summaries: list[str] = []

        def _run_one(goal: str) -> str:
            return self.run_from_tool(
                {
                    "goal": goal,
                    "context": context,
                    "archetype": "explore",
                    "success_criteria": success_criteria,
                },
                spawn_context,
                working_dir,
                progress_callback=progress_callback,
            )

        pool = ThreadPoolExecutor(max_workers=min(len(goals), MAX_PARALLEL_EXPLORE))
        try:
            futures = [pool.submit(_run_one, goal) for goal in goals]
            # 使用总超时而非 per-future 超时，避免多个 future 累积等待
            done, not_done = futures_wait(futures, timeout=SUBAGENT_TIMEOUT_SEC)
            for future in futures:
                if future in done:
                    summaries.append(future.result())
                else:
                    summaries.append(
                        f"Error: sub-agent timed out after {SUBAGENT_TIMEOUT_SEC}s."
                    )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        return "\n\n---\n\n".join(summaries)

    @staticmethod
    def _wrap_progress(
        callback: Callable[[ProgressEvent], None] | None,
        sub_run_id: str,
        archetype: str,
    ) -> Callable[[ProgressEvent], None] | None:
        if callback is None:
            return None

        def wrapped(event: ProgressEvent) -> None:
            try:
                callback(
                    ProgressEvent(
                        kind=event.kind,
                        iteration=event.iteration,
                        message=event.message,
                        tool_name=event.tool_name,
                        success=event.success,
                        detail=event.detail,
                        sub_run_id=sub_run_id,
                        archetype=archetype,
                    )
                )
            except Exception as exc:  # pragma: no cover
                logger.debug("Sub-agent progress callback failed: %s", exc)

        return wrapped

    @staticmethod
    def _emit(
        callback: Callable[[ProgressEvent], None] | None,
        event: ProgressEvent,
    ) -> None:
        if callback is None:
            return
        try:
            callback(event)
        except Exception as exc:  # pragma: no cover
            logger.debug("Sub-agent progress callback failed: %s", exc)


MAX_MESSAGE_LEN = 2000


def _parse_parallel_goals(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    goals: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            goals.append(text)
        if len(goals) >= MAX_PARALLEL_EXPLORE:
            break
    return goals if len(goals) >= 2 else []
