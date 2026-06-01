"""Format child loop results for parent tool messages."""

from __future__ import annotations

from secretary.agent.loop import MAX_TOOL_OUTPUT_CHARS, LoopResult


def format_subagent_result(
    result: LoopResult,
    *,
    run_id: str,
    archetype: str,
) -> str:
    lines = [f"[subagent:{archetype}:{run_id}]"]
    reply = result.reply.strip()
    if reply:
        lines.append(reply)
    if result.files_read:
        lines.append("Files read: " + ", ".join(result.files_read[:20]))
    if result.used_tools:
        lines.append("Tools used: " + ", ".join(result.used_tools))
    if result.pending_confirmation:
        lines.append(
            "Note: sub-agent stopped for user confirmation; "
            f"{result.pending_confirmation.description}"
        )
    text = "\n\n".join(lines)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        return text[:MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"
    return text
