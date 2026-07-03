"""In-memory active turn registry keyed by client trace id."""

from __future__ import annotations

import threading

from secretary.agent.turn_models import TurnContext, TurnStatus


class SessionStore:
    def __init__(self) -> None:
        self._turns: dict[str, TurnContext] = {}
        self._lock = threading.Lock()

    def start_turn(
        self,
        *,
        trace_id: str,
        thread_id: str = "",
        user_message: str = "",
        parent_turn_id: str = "",
        child_id: str = "",
    ) -> TurnContext:
        turn = TurnContext.create(
            trace_id=trace_id,
            thread_id=thread_id,
            user_message=user_message,
            parent_turn_id=parent_turn_id,
            child_id=child_id,
        )
        with self._lock:
            self._turns[trace_id] = turn
        return turn

    def get_turn(self, trace_id: str) -> TurnContext | None:
        if not trace_id:
            return None
        with self._lock:
            return self._turns.get(trace_id)

    def end_turn(self, trace_id: str, *, status: TurnStatus = "completed") -> None:
        if not trace_id:
            return
        with self._lock:
            turn = self._turns.get(trace_id)
            if turn is not None:
                turn.status = status

    def clear_turn(self, trace_id: str) -> None:
        if not trace_id:
            return
        with self._lock:
            self._turns.pop(trace_id, None)
