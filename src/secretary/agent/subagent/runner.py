"""Run isolated child AgentLoop instances for delegated tasks."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.policy import (
    MAX_PARALLEL_EXPLORE,
    MAX_SPAWNS_PER_TURN,
    MAX_SPAWN_DEPTH,
    SUBAGENT_TIMEOUT_SEC,
)
from secretary.agent.subagent.registry import (
    build_messages,
    get_archetype,
    list_archetype_names,
    resolve_tools,
)
from secretary.agent.subagent.summarize import format_subagent_result
from secretary.memory.db import MemoryStore
from secretary.memory.hermes_memory import HermesMemory
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubAgentDeps:
    llm_config: LlmConfig
    file_auth: FileAuthService | None
    memory_store: MemoryStore
    hermes: HermesMemory
    lumina_dir: Path | None = None
    temperature: float = 0.3


class SubAgentRunner:
    def __init__(self, deps: SubAgentDeps) -> None:
        self._deps = deps

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
        if parallel_goals:
            if archetype != "explore":
                return "Error: parallel goals are only supported for archetype 'explore'."
            return self._run_parallel_explore(
                parallel_goals,
                context=context,
                spawn_context=spawn_context,
                working_dir=working_dir,
                progress_callback=progress_callback,
            )
        if not goal:
            return "Error: spawn_subagent requires a non-empty goal."

        policy_error = self._check_policy(spawn_context, archetype)
        if policy_error:
            return policy_error

        spec = get_archetype(archetype, self._deps.lumina_dir)
        if spec is None:
            supported = ", ".join(list_archetype_names(self._deps.lumina_dir))
            return f"Error: unknown or unsupported archetype '{archetype}'. Supported: {supported}."

        run_id = uuid.uuid4().hex[:12]
        child_session_id = spawn_context.child_session_id(run_id)
        spawn_context.record_spawn()

        self._emit(
            progress_callback,
            ProgressEvent(
                kind="subagent_started",
                iteration=0,
                message=f"正在派生子 Agent ({archetype})：{goal[:100]}",
                sub_run_id=run_id,
                archetype=archetype,
            ),
        )

        tools = resolve_tools(archetype, self._deps)
        messages = build_messages(goal=goal, context=context, spec=spec)
        wrapped_progress = self._wrap_progress(progress_callback, run_id, archetype)

        try:
            self._deps.hermes.create_session(child_session_id)
            self._deps.hermes.add_message(child_session_id, "user", goal[:MAX_MESSAGE_LEN])
            summary = self._run_child_loop(
                messages=messages,
                tools=tools,
                max_steps=spec.max_steps,
                working_dir=working_dir,
                progress_callback=wrapped_progress,
                run_id=run_id,
                archetype=archetype,
            )
            self._deps.hermes.add_message(child_session_id, "assistant", summary[:MAX_MESSAGE_LEN])
            self._deps.hermes.end_session(child_session_id, summary=summary[:200])
        except FuturesTimeoutError:
            summary = f"Error: sub-agent timed out after {SUBAGENT_TIMEOUT_SEC}s."
            success = False
        except Exception as exc:
            logger.warning("Sub-agent run failed: %s", exc)
            summary = f"Error: sub-agent failed: {exc}"
            success = False
        else:
            success = not summary.startswith("Error:")

        self._emit(
            progress_callback,
            ProgressEvent(
                kind="subagent_finished",
                iteration=0,
                message=summary[:200],
                sub_run_id=run_id,
                archetype=archetype,
                success=success,
            ),
        )
        return summary

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
    ) -> str:
        loop = AgentLoop(
            self._deps.llm_config,
            tools=tools,
            max_steps=max_steps,
            file_auth=self._deps.file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
        )

        def _execute() -> str:
            result = loop.run(messages, temperature=self._deps.temperature)
            return format_subagent_result(result, run_id=run_id, archetype=archetype)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_execute)
            return future.result(timeout=SUBAGENT_TIMEOUT_SEC)

    def _check_policy(self, spawn_context: SpawnContext, archetype: str) -> str | None:
        if spawn_context.depth >= MAX_SPAWN_DEPTH:
            return (
                f"Error: spawn depth limit reached ({MAX_SPAWN_DEPTH}). "
                "Sub-agents cannot spawn further sub-agents."
            )
        if spawn_context.spawns_this_turn >= MAX_SPAWNS_PER_TURN:
            return (
                f"Error: spawn quota exceeded ({MAX_SPAWNS_PER_TURN} per turn). "
                "Finish current sub-tasks before delegating more."
            )
        if get_archetype(archetype, self._deps.lumina_dir) is None:
            return f"Error: unknown archetype '{archetype}'."
        return None

    def _run_parallel_explore(
        self,
        goals: list[str],
        *,
        context: str,
        spawn_context: SpawnContext,
        working_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None,
    ) -> str:
        if spawn_context.depth >= MAX_SPAWN_DEPTH:
            return f"Error: spawn depth limit reached ({MAX_SPAWN_DEPTH})."
        remaining = MAX_SPAWNS_PER_TURN - spawn_context.spawns_this_turn
        if remaining < len(goals):
            return (
                f"Error: spawn quota exceeded; need {len(goals)} slots, "
                f"{remaining} remaining ({MAX_SPAWNS_PER_TURN} per turn)."
            )

        summaries: list[str] = []

        def _run_one(goal: str) -> str:
            return self.run_from_tool(
                {"goal": goal, "context": context, "archetype": "explore"},
                spawn_context,
                working_dir,
                progress_callback=progress_callback,
            )

        with ThreadPoolExecutor(max_workers=min(len(goals), MAX_PARALLEL_EXPLORE)) as pool:
            futures = [pool.submit(_run_one, goal) for goal in goals]
            for future in futures:
                summaries.append(future.result(timeout=SUBAGENT_TIMEOUT_SEC))

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
