"""Pure helpers for tool-call message assembly and untrusted output wrapping."""

from __future__ import annotations

import json
from typing import Any

from secretary.agent.tools.base import ToolCall

# External data may contain prompt injection; delimit and instruct the model
# not to follow instructions inside the markers.
_UNTRUSTED_TOOLS = frozenset({"web_search", "web_fetch", "file_read", "read"})
_UNTRUSTED_BEGIN = "<untrusted_external_content>"
_UNTRUSTED_END = "</untrusted_external_content>"


def wrap_untrusted(tool_name: str, content: str) -> str:
    """Wrap external-tool output so the model treats it as data, not instructions."""
    if tool_name not in _UNTRUSTED_TOOLS:
        return content
    return f"{_UNTRUSTED_BEGIN}\n{content}\n{_UNTRUSTED_END}"


def classify_tool_error(exc: Exception) -> tuple[str, bool]:
    """Classify a tool exception as (error_type, retryable).

    error_type: not_found / permission / timeout / validation / internal
    """
    exc_name = type(exc).__name__
    exc_msg = str(exc).lower()
    if "timeout" in exc_name.lower() or "timeout" in exc_msg or "timed out" in exc_msg:
        return "timeout", True
    if (
        "notfound" in exc_name.lower()
        or "not found" in exc_msg
        or "no such file" in exc_msg
        or "does not exist" in exc_msg
    ):
        return "not_found", False
    if (
        "permission" in exc_name.lower()
        or "permission" in exc_msg
        or "denied" in exc_msg
        or "forbidden" in exc_msg
    ):
        return "permission", False
    if (
        "valueerror" in exc_name.lower()
        or "typeerror" in exc_name.lower()
        or "keyerror" in exc_name.lower()
    ):
        return "validation", False
    return "internal", False


def ensure_tool_call_id(tool_call: ToolCall, *, suffix: str) -> ToolCall:
    call_id = tool_call.id.strip()
    if call_id:
        return tool_call
    return ToolCall(
        name=tool_call.name,
        arguments=tool_call.arguments,
        id=f"call_{tool_call.name}_{suffix}",
    )


def assistant_message_for_tool_call(
    assistant_message: dict[str, Any],
    tool_call: ToolCall,
) -> dict[str, Any]:
    """Build an assistant message paired with exactly one tool response."""
    content = assistant_message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    result: dict[str, Any] = {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                },
            }
        ],
    }
    # DeepSeek thinking mode: tool-call turns must replay reasoning_content.
    reasoning = assistant_message.get("reasoning_content")
    if isinstance(reasoning, str):
        result["reasoning_content"] = reasoning
    return result


def assistant_message_for_batch(
    assistant_message: dict[str, Any],
    tool_calls: list[ToolCall],
) -> dict[str, Any]:
    """Build one assistant message listing all tool_calls for native batch replay."""
    content = assistant_message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    result: dict[str, Any] = {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in tool_calls
        ],
    }
    reasoning = assistant_message.get("reasoning_content")
    if isinstance(reasoning, str):
        result["reasoning_content"] = reasoning
    return result
