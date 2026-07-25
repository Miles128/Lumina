"""Shared FastAPI dependencies and chat/MCP helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request

from secretary.agent.chat_service import ChatResult
from secretary.agent.llm_client import LlmUsage
from secretary.agent.mcp_manager import McpManager
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.progress_hub import ProgressHub
from secretary.api.schemas import ChatResponse


def to_chat_response(result: ChatResult, usage: LlmUsage | None = None) -> ChatResponse:
    pending = result.pending_confirmation
    usage_stats = usage or LlmUsage()
    return ChatResponse(
        reply=result.reply,
        profile_excerpt=result.profile_excerpt,
        used_tools=result.used_tools or [],
        total_steps=result.total_steps,
        route=result.route,
        needs_confirmation=pending is not None,
        confirmation_description=pending.description if pending else "",
        confirmation_action_id=pending.action_id if pending else "",
        confirmation_risk_level=pending.risk_level if pending else "",
        confirmation_kind=result.confirmation_kind,
        confirmation_diff=(pending.diff_preview if pending else "") or "",
        allow_permanent_read=result.allow_permanent_read,
        allow_session_write=result.allow_session_write,
        grounding_verified=result.grounding_verified,
        grounding_note=result.grounding_note,
        files_read=list(result.files_read or []),
        usage_prompt_tokens=usage_stats.prompt_tokens,
        usage_completion_tokens=usage_stats.completion_tokens,
        usage_total_tokens=usage_stats.total_tokens,
        confirmation_scope=result.confirmation_scope,
        raw_reply=result.raw_reply,
    )



def svc(request: Request) -> Any:
    return request.app.state


def build_progress_callback(
    request: Request,
    trace_id: str,
) -> Callable[[ProgressEvent], None] | None:
    if not trace_id:
        return None
    hub: ProgressHub = request.app.state.progress_hub
    hub.open(trace_id)
    trace_store = getattr(request.app.state, "trace_store", None)
    retention = "full"
    agent_config_store = getattr(request.app.state, "agent_config_store", None)
    if agent_config_store is not None:
        try:
            retention = agent_config_store.load().harness.trace_retention
        except Exception:
            retention = "full"

    def callback(event: ProgressEvent) -> None:
        hub.publish(trace_id, event)
        if trace_store is not None:
            try:
                trace_store.append(trace_id, event, retention=retention)
            except Exception:
                pass

    return callback


def finish_progress(request: Request, trace_id: str, *, keep_turn: bool = False) -> None:
    if not trace_id:
        return
    request.app.state.progress_hub.close(trace_id)
    if not keep_turn:
        request.app.state.session_store.clear_turn(trace_id)


def build_builtin_provider_summaries(manager: McpManager) -> list[dict[str, object]]:
    """Build a status summary for each builtin MCP provider (connector).

    Iterates the builtin registry and calls ``mcp_{name}_status`` on each
    provider to read its stored health. Used by both ``/api/mcp/builtin``
    and ``/api/mcp/status`` so the frontend can render the unified MCP pane
    in a single fetch.
    """
    providers: list[dict[str, object]] = []
    for p in manager._builtin.list_providers():
        status = manager.call_tool(f"mcp_{p.name}_status", {})
        if not isinstance(status, dict):
            status = {}
        providers.append({
            "name": p.name,
            "display_name": p.display_name,
            "configured": status.get("configured", False),
            "status": status.get("status", "unknown"),
            "message": status.get("message", ""),
            "item_count": status.get("item_count", 0),
            "last_sync_at": status.get("last_sync_at"),
        })
    return providers

