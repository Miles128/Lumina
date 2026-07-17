"""Unified delegation results for spawn_subagent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from secretary.agent.loop import MAX_TOOL_OUTPUT_CHARS, LoopResult
from secretary.agent.text_utils import truncate_chars

DelegationKind = Literal["subagent", "cli"]
DelegationStatus = Literal["done", "failed", "paused"]


@dataclass(frozen=True)
class DelegationResult:
    kind: DelegationKind
    run_id: str
    provider: str
    goal: str
    summary: str
    success: bool
    status: DelegationStatus
    used_tools: tuple[str, ...] = ()
    files_read: tuple[str, ...] = ()
    detail: str = ""

    def to_tool_output(self) -> str:
        tag = f"[{self.kind}:{self.provider}:{self.run_id}]"
        status_line = self.status if self.success else f"{self.status} · {self.detail}".strip()
        lines = [tag, f"Status: {status_line}"]
        body = self.summary.strip()
        if body:
            lines.append(body)
        if self.files_read:
            lines.append("Files read: " + ", ".join(self.files_read[:20]))
        if self.used_tools:
            lines.append("Tools used: " + ", ".join(self.used_tools))
        return truncate_chars("\n\n".join(lines), MAX_TOOL_OUTPUT_CHARS)


def delegation_from_loop_result(
    result: LoopResult,
    *,
    run_id: str,
    provider: str,
    goal: str,
) -> DelegationResult:
    if result.pending_confirmation:
        return DelegationResult(
            kind="subagent",
            run_id=run_id,
            provider=provider,
            goal=goal,
            summary=result.reply.strip(),
            success=False,
            status="paused",
            used_tools=tuple(result.used_tools),
            files_read=tuple(result.files_read),
            detail=result.pending_confirmation.description,
        )
    reply = result.reply.strip()
    failed = reply.startswith("Error:") or not reply
    return DelegationResult(
        kind="subagent",
        run_id=run_id,
        provider=provider,
        goal=goal,
        summary=reply,
        success=not failed,
        status="failed" if failed else "done",
        used_tools=tuple(result.used_tools),
        files_read=tuple(result.files_read),
    )


def delegation_from_cli(
    *,
    run_id: str,
    provider: str,
    goal: str,
    summary: str,
    success: bool,
    exit_code: int,
) -> DelegationResult:
    status: DelegationStatus = "done" if success else "failed"
    return DelegationResult(
        kind="cli",
        run_id=run_id,
        provider=provider,
        goal=goal,
        summary=summary.strip(),
        success=success,
        status=status,
        detail=f"exit={exit_code}",
    )


def format_subagent_result(
    result: LoopResult,
    *,
    run_id: str,
    archetype: str,
    goal: str = "",
) -> str:
    """Backward-compatible wrapper around DelegationResult."""
    return delegation_from_loop_result(
        result,
        run_id=run_id,
        provider=archetype,
        goal=goal,
    ).to_tool_output()
