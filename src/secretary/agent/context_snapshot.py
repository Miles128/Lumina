"""Build assembled-context snapshots for harness UI observability."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from secretary.agent.context_compaction import estimate_messages_tokens
from secretary.agent.llm_client import LlmUsage


def _message_content_text(message: dict[str, Any]) -> str:
    """Flatten a chat message into displayable text (model-facing content)."""
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str) and content:
        parts.append(content)
    elif isinstance(content, list):
        # Multimodal / content-parts style
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
            elif isinstance(part, str):
                chunks.append(part)
        if chunks:
            parts.append("\n".join(chunks))
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        parts.append(json.dumps(tool_calls, ensure_ascii=False, indent=2))
    name = message.get("name")
    if isinstance(name, str) and name and message.get("role") == "tool":
        # Keep tool name visible when present
        if parts:
            parts[0] = f"[{name}]\n{parts[0]}"
        else:
            parts.append(f"[{name}]")
    return "\n".join(parts)


def _approx_tokens_for_text(text: str) -> int:
    if not text:
        return 0
    return estimate_messages_tokens([{"role": "user", "content": text}])


def build_context_snapshot(
    messages: list[dict[str, Any]] | None,
    *,
    trace_id: str = "",
    thread_id: str = "",
    usage: LlmUsage | None = None,
    compaction_before: int | None = None,
    compaction_after: int | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Serialize assembled LLM messages + usage for the desktop context panel."""
    usage = usage or LlmUsage()
    rows: list[dict[str, Any]] = []
    for index, message in enumerate(messages or []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown")
        content = _message_content_text(message)
        rows.append(
            {
                "index": index,
                "role": role,
                "content": content,
                "approx_tokens": _approx_tokens_for_text(content),
            }
        )
    estimated = estimate_messages_tokens(list(messages or []))
    return {
        "trace_id": trace_id or "",
        "thread_id": thread_id or "",
        "captured_at": captured_at or datetime.now(UTC).isoformat(),
        "usage": {
            "prompt_tokens": int(usage.prompt_tokens or 0),
            "completion_tokens": int(usage.completion_tokens or 0),
            "total_tokens": int(usage.total_tokens or 0),
            "cache_hit_tokens": int(usage.prompt_cache_hit_tokens or 0) or None,
            "cache_miss_tokens": int(usage.prompt_cache_miss_tokens or 0) or None,
            "estimated_prompt_tokens": estimated,
        },
        "compaction": {
            "before_tokens": compaction_before,
            "after_tokens": compaction_after,
        },
        "messages": rows,
        "message_count": len(rows),
        "approx_total_tokens": estimated,
    }
