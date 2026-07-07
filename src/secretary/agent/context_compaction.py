"""Compact long agent-loop message history (Codex turn compaction semantics)."""

from __future__ import annotations

import logging
from typing import Any

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError

logger = logging.getLogger(__name__)

LOOP_CONTEXT_MAX_CHARS = 32_000
COMPACT_THRESHOLD_RATIO = 0.85
KEEP_TAIL_MESSAGES = 8

_COMPACT_SYSTEM = """你是 Agent 对话历史压缩器。将较早的对话与工具上下文压缩成一段简短摘要。
要求：
- 保留用户目标、已确认决策、关键事实、文件路径、工具结论
- 删除重复、寒暄、失败重试细节
- 输出不超过 {max_chars} 个字符
- 直接输出摘要正文，不要 JSON、不要标题前缀"""


def estimate_messages_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            total += len(str(tool_calls))
    return total


def compact_messages_if_needed(
    messages: list[dict[str, Any]],
    llm_config: LlmConfig | None,
    *,
    max_chars: int = LOOP_CONTEXT_MAX_CHARS,
    keep_tail: int = KEEP_TAIL_MESSAGES,
) -> list[dict[str, Any]]:
    """Return messages unchanged or with middle history replaced by a summary block."""
    if not messages:
        return messages
    threshold = int(max_chars * COMPACT_THRESHOLD_RATIO)
    if estimate_messages_chars(messages) <= threshold:
        return messages

    system_msgs = [msg for msg in messages if msg.get("role") == "system"]
    non_system = [msg for msg in messages if msg.get("role") != "system"]
    if len(non_system) <= keep_tail + 1:
        return messages

    head = non_system[:-keep_tail]
    tail = non_system[-keep_tail:]
    summary = _summarize_block(head, llm_config, max_chars=max(1200, max_chars // 6))
    compacted = [*system_msgs]
    compacted.append(
        {
            "role": "user",
            "content": (
                "[System] Earlier conversation was compacted to save context:\n"
                f"{summary}\n\n"
                "Continue from the recent messages below."
            ),
        }
    )
    compacted.extend(tail)
    if estimate_messages_chars(compacted) > max_chars:
        return _truncate_fallback(system_msgs, tail, max_chars=max_chars)
    logger.info(
        "compacted agent context: %s -> %s chars",
        estimate_messages_chars(messages),
        estimate_messages_chars(compacted),
    )
    return compacted


def _summarize_block(
    messages: list[dict[str, Any]],
    llm_config: LlmConfig | None,
    *,
    max_chars: int,
) -> str:
    if llm_config is not None:
        body = _format_messages_for_summary(messages)
        if body.strip():
            try:
                summary = chat_completion(
                    llm_config,
                    [
                        {
                            "role": "system",
                            "content": _COMPACT_SYSTEM.format(max_chars=max_chars),
                        },
                        {"role": "user", "content": body[:24_000]},
                    ],
                    temperature=0.0,
                    timeout=45.0,
                ).strip()
                if summary and len(summary) <= max_chars * 1.2:
                    return summary[:max_chars]
            except AgentError as exc:
                logger.warning("LLM context compaction skipped: %s", exc)
    return _rule_summary(messages, max_chars=max_chars)


def _format_messages_for_summary(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "unknown")
        content = message.get("content")
        text = content.strip() if isinstance(content, str) else ""
        if not text and role == "assistant" and message.get("tool_calls"):
            text = "[tool call]"
        if text:
            lines.append(f"{role}: {text[:2000]}")
    return "\n".join(lines)


def _rule_summary(messages: list[dict[str, Any]], *, max_chars: int) -> str:
    snippets: list[str] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        text = content.strip().replace("\n", " ")
        if len(text) > 180:
            text = text[:180] + "…"
        snippets.append(f"- ({role}) {text}")
    summary = "\n".join(snippets)
    if len(summary) > max_chars:
        return summary[: max_chars - 1] + "…"
    return summary or "(no prior context)"


def _truncate_fallback(
    system_msgs: list[dict[str, Any]],
    tail: list[dict[str, Any]],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = list(system_msgs)
    compacted.append(
        {
            "role": "user",
            "content": "[System] Earlier context truncated due to size limits.",
        }
    )
    budget = max_chars - estimate_messages_chars(compacted)
    for message in tail:
        content = message.get("content")
        if isinstance(content, str) and len(content) > budget // max(len(tail), 1):
            trimmed = dict(message)
            trimmed["content"] = content[: max(200, budget // max(len(tail), 1))] + "\n…[truncated]"
            compacted.append(trimmed)
        else:
            compacted.append(message)
    return compacted
