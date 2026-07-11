"""Loop stop hooks for policy-driven halts/sanitization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LoopSnapshot:
    iteration: int
    max_iterations: int
    latest_user_message: str


@dataclass(frozen=True)
class StopDecision:
    should_stop: bool
    reason: str = ""


class StopHook(Protocol):
    def before_iteration(self, snapshot: LoopSnapshot) -> StopDecision: ...

    def sanitize_reply(self, reply: str, snapshot: LoopSnapshot) -> str: ...


class MaxIterationsStopHook:
    """Hard cap iterations regardless of loop configuration."""

    def __init__(self, max_iterations: int) -> None:
        self._max_iterations = max(1, max_iterations)

    def before_iteration(self, snapshot: LoopSnapshot) -> StopDecision:
        if snapshot.iteration > self._max_iterations:
            return StopDecision(
                should_stop=True,
                reason=f"已达到安全步数上限（{self._max_iterations}）",
            )
        return StopDecision(should_stop=False)

    def sanitize_reply(self, reply: str, snapshot: LoopSnapshot) -> str:
        return reply
