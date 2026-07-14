"""Turn-scoped wrapper around TurnOrchestrator (Harness P0)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import LoopResult
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.session_store import SessionStore
from secretary.agent.turn_models import TurnContext
from secretary.agent.turn_orchestrator import AgentTurnPlan, TurnOrchestrator


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


class TurnRunner:
    """Runs agent loops inside a Turn lifecycle with turn_* progress events."""

    def __init__(
        self,
        orchestrator: TurnOrchestrator,
        session_store: SessionStore | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._session_store = session_store or SessionStore()

    @property
    def orchestrator(self) -> TurnOrchestrator:
        return self._orchestrator

    @property
    def session_store(self) -> SessionStore:
        return self._session_store

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
            result = self._orchestrator.run_agent_turn(
                llm_config,
                plan,
                temperature=temperature,
                working_dir=working_dir,
                progress_callback=wrapped,
                on_subagent_paused=on_subagent_paused,
                cancel_check=cancel_check,
            )
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
        tools: list[Any],
        pending: Any,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        turn: TurnContext | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> LoopResult:
        wrapped = bind_turn_progress(progress_callback, turn)
        return self._orchestrator.run_confirmed_action(
            llm_config,
            tools,
            pending,
            messages,
            temperature=temperature,
            working_dir=working_dir,
            progress_callback=wrapped,
            cancel_check=cancel_check,
        )

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
        return self._orchestrator.resume_after_subagent(
            llm_config,
            resume,
            tool_output,
            temperature=temperature,
            working_dir=working_dir,
            progress_callback=wrapped,
            on_subagent_paused=on_subagent_paused,
            cancel_check=cancel_check,
        )
