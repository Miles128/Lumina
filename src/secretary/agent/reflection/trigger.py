"""F21 Reflexion: heuristic failure detection for Build-profile turns.

Evaluates a completed turn against 5 failure signals (priority order:
F4 max_steps → F2 verify_failed → F1 user_correction → F3 grounding → F5 aborted).
Returns the first matching FailureSignal, or None if no failure detected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from secretary.agent.loop import LoopResult

logger = logging.getLogger(__name__)

# F1: user correction keywords (Chinese + English)
_CORRECTION_KEYWORDS = frozenset({
    "不对", "错了", "重新", "撤销", "不要这样", "不要这样改", "这不是我要的",
    "revert", "rollback", "undo", "redo",
})

# F2: verify sub-agent failure markers
_VERIFY_FAIL_MARKERS = ("pass: false", "fail", "issues found")


@dataclass
class FailureSignal:
    """Detected failure context, passed to the reflect sub-agent."""

    mode: str  # user_correction | verify_failed | grounding_failed | max_steps_exhausted | turn_aborted
    summary: str
    user_message: str
    raw_reply: str
    tool_calls_summary: list[str] = field(default_factory=list)
    verify_issues: str | None = None


class ReflectionTrigger:
    """Heuristic failure detector. Stateless; safe to reuse across turns."""

    def __init__(self, max_steps: int = 20) -> None:
        self._max_steps = max_steps

    def evaluate(
        self,
        *,
        profile: str,
        user_message: str,
        raw_reply: str,
        loop_result: LoopResult,
        turn_status: str,
        tool_call_history: list[dict[str, Any]],
    ) -> FailureSignal | None:
        """Check failure signals in priority order. Returns first match or None."""
        # Only Build profile triggers reflection
        if profile != "build":
            return None

        tool_summary = self._summarize_tool_calls(tool_call_history)

        # F4: max steps exhausted (most fundamental failure)
        if loop_result.total_steps >= self._max_steps:
            return FailureSignal(
                mode="max_steps_exhausted",
                summary=f"Turn exhausted all {self._max_steps} steps without finalizing",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        # F2: verify sub-agent returned Fail
        verify_issues = self._check_verify_failure(tool_call_history)
        if verify_issues is not None:
            return FailureSignal(
                mode="verify_failed",
                summary="Verify sub-agent reported failure",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
                verify_issues=verify_issues,
            )

        # F1: user correction keyword (only in Build)
        if self._has_correction_keyword(user_message):
            return FailureSignal(
                mode="user_correction",
                summary="User explicitly corrected the previous turn",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        # F3: grounding not verified
        if not loop_result.grounding_verified:
            return FailureSignal(
                mode="grounding_failed",
                summary="Reply failed grounding verification",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        # F5: turn aborted (cancelled or failed)
        if loop_result.cancelled or turn_status in ("failed", "cancelled"):
            return FailureSignal(
                mode="turn_aborted",
                summary=f"Turn ended with status: {turn_status}",
                user_message=user_message,
                raw_reply=raw_reply[:2000],
                tool_calls_summary=tool_summary,
            )

        return None

    def _has_correction_keyword(self, message: str) -> bool:
        lower = message.lower()
        return any(kw in lower for kw in _CORRECTION_KEYWORDS)

    def _check_verify_failure(self, tool_history: list[dict[str, Any]]) -> str | None:
        """Scan tool calls for verify sub-agent failures. Returns issues text or None."""
        for call in tool_history:
            args = call.get("arguments", {})
            if args.get("archetype") != "verify":
                continue
            output = str(call.get("output", "")).lower()
            if any(marker in output for marker in _VERIFY_FAIL_MARKERS):
                return str(call.get("output", ""))
        return None

    def _summarize_tool_calls(self, tool_history: list[dict[str, Any]]) -> list[str]:
        """Build compact summaries of tool calls for the reflector."""
        summaries: list[str] = []
        for call in tool_history:
            name = call.get("name", "unknown")
            output = str(call.get("output", ""))[:150]
            summaries.append(f"{name}: {output}")
        return summaries
