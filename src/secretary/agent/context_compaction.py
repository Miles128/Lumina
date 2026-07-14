"""Compact long agent-loop message history (Codex turn compaction semantics).

Token-based budgeting is primary (tiktoken when available, char//3 heuristic fallback).
The legacy `max_chars` parameter is kept for backward compatibility and is converted
to a token budget via `max_chars // 3` when explicitly supplied.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError

logger = logging.getLogger(__name__)

# Token-based limit (primary). Targets 128k-context models; 24k history budget
# leaves ~100k for system prompt, tool schemas, tool outputs, and reply.
LOOP_CONTEXT_MAX_TOKENS = 24_000
# Legacy char-based limit (fallback only, used when callers pass max_chars).
LOOP_CONTEXT_MAX_CHARS = 32_000
COMPACT_THRESHOLD_RATIO = 0.85
KEEP_TAIL_MESSAGES = 8

# 当工具结果超过此字符数时，在深层历史中用占位符替换以释放上下文空间。
_TOOL_RESULT_CLEAR_THRESHOLD = 500
_TOOL_RESULT_CLEARED_PLACEHOLDER = "[Tool Result cleared — see summary above]"

# Rough char→token conversion when tiktoken is unavailable.
# Mixed CJK+English averages ~3 chars/token (CJK ~1.5 chars/token, English ~4).
_CHARS_PER_TOKEN_FALLBACK = 3

CompactionMode = Literal[
    "none",
    "clear_tools",
    "llm_summary",
    "rule_summary",
    "truncate",
]

_COMPACT_SYSTEM = """你是 Agent 对话历史压缩器。将较早的对话与工具上下文压缩成一段简短摘要。
要求：
- 保留用户目标、已确认决策、关键事实、文件路径、工具结论
- 删除重复、寒暄、失败重试细节
- 输出不超过 {max_chars} 个字符
- 直接输出摘要正文，不要 JSON、不要标题前缀"""


@dataclass(frozen=True)
class CompactionResult:
    """Outcome of a compaction pass (messages + observability metrics)."""

    messages: list[dict[str, Any]]
    triggered: bool = False
    mode: CompactionMode = "none"
    before_tokens: int = 0
    after_tokens: int = 0
    tool_results_cleared: int = 0
    truncated: bool = False

    def to_detail(self) -> str:
        return json.dumps(
            {
                "triggered": self.triggered,
                "mode": self.mode,
                "before_tokens": self.before_tokens,
                "after_tokens": self.after_tokens,
                "tool_results_cleared": self.tool_results_cleared,
                "truncated": self.truncated,
            },
            ensure_ascii=False,
        )


@lru_cache(maxsize=1)
def _get_tiktoken_encoder() -> Any:
    """Lazily load tiktoken cl100k_base encoder. Returns None if unavailable."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        logger.debug("tiktoken unavailable, falling back to char heuristic: %s", exc)
        return None


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count for messages.

    Uses tiktoken cl100k_base when available for accuracy. Falls back to
    `estimate_messages_chars // 3` heuristic for mixed CJK+English content.
    """
    encoder = _get_tiktoken_encoder()
    if encoder is not None:
        total = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                total += len(encoder.encode(content))
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                # 使用 json.dumps 编码以匹配实际 API 传输格式，避免 str()
                # 产生的 Python repr（花括号、引号、单引号转义等）导致 token 膨胀。
                total += len(encoder.encode(json.dumps(tool_calls, ensure_ascii=False)))
            # Per-message structural overhead (~4 tokens for role/separator).
            total += 4
        return total
    return estimate_messages_chars(messages) // _CHARS_PER_TOKEN_FALLBACK


def estimate_messages_chars(messages: list[dict[str, Any]]) -> int:
    """Legacy char-count estimate. Retained for tests and backward compat."""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            total += len(str(tool_calls))
    return total


def clear_old_tool_results(
    messages: list[dict[str, Any]],
    *,
    keep_tail: int = KEEP_TAIL_MESSAGES,
) -> tuple[list[dict[str, Any]], int]:
    """Replace large tool results in deep history with a placeholder.

    Returns ``(messages, cleared_count)``.
    """
    if len(messages) <= keep_tail + 1:
        return messages, 0

    result = list(messages)
    tail_start = len(result) - keep_tail
    cleared = 0

    for i in range(tail_start):
        msg = result[i]
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(content, str):
            continue

        # Native tool messages: role=tool
        if role == "tool" and len(content) > _TOOL_RESULT_CLEAR_THRESHOLD:
            cleared_msg = dict(msg)
            cleared_msg["content"] = _TOOL_RESULT_CLEARED_PLACEHOLDER
            result[i] = cleared_msg
            cleared += 1
            continue

        # Text-mode tool results: user messages starting with "[Tool Result:"
        if role == "user" and content.startswith("[Tool Result:"):
            # Extract tool name for traceability
            first_line = content.split("\n", 1)[0]
            if len(content) > _TOOL_RESULT_CLEAR_THRESHOLD:
                cleared_msg = dict(msg)
                cleared_msg["content"] = f"{first_line}\n{_TOOL_RESULT_CLEARED_PLACEHOLDER}"
                result[i] = cleared_msg
                cleared += 1

    return result, cleared


def compact_messages_if_needed(
    messages: list[dict[str, Any]],
    llm_config: LlmConfig | None,
    *,
    max_tokens: int = LOOP_CONTEXT_MAX_TOKENS,
    keep_tail: int = KEEP_TAIL_MESSAGES,
    max_chars: int | None = None,
) -> CompactionResult:
    """Return messages unchanged or with middle history replaced by a summary block.

    Token-based budgeting is primary. If `max_chars` is explicitly provided
    (backward compat), it is converted to a token budget via `max_chars // 3`.

    优先级：当 ``max_chars`` 非 None 时，它覆盖 ``max_tokens``（向后兼容语义）。
    同时传入两个参数通常意味着调用方意图不明确，会触发一条 warning 日志。

    Before full LLM-based compaction, large tool results in deep history are
    replaced with placeholders (``clear_old_tool_results``) to reduce token
    pressure without losing recent context.
    """
    if not messages:
        return CompactionResult(messages=messages)

    if max_chars is not None:
        # max_chars 优先级高于 max_tokens：显式传入 max_chars 时覆盖 max_tokens，
        # 以保持向后兼容（老调用方只传 max_chars）。
        if max_chars // _CHARS_PER_TOKEN_FALLBACK != max_tokens:
            logger.warning(
                "compact_messages_if_needed: both max_chars=%s and max_tokens=%s "
                "supplied; using max_chars-derived budget (max_chars takes priority)",
                max_chars,
                max_tokens,
            )
        token_budget = max_chars // _CHARS_PER_TOKEN_FALLBACK
    else:
        token_budget = max_tokens
    threshold = int(token_budget * COMPACT_THRESHOLD_RATIO)

    # Step 1: clear old tool results to reduce token pressure early.
    messages, cleared_count = clear_old_tool_results(messages, keep_tail=keep_tail)

    before_tokens = estimate_messages_tokens(messages)
    if before_tokens <= threshold:
        mode: CompactionMode = "clear_tools" if cleared_count else "none"
        return CompactionResult(
            messages=messages,
            triggered=cleared_count > 0,
            mode=mode,
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            tool_results_cleared=cleared_count,
        )

    system_msgs = [msg for msg in messages if msg.get("role") == "system"]
    non_system = [msg for msg in messages if msg.get("role") != "system"]
    if len(non_system) <= keep_tail + 1:
        return CompactionResult(
            messages=messages,
            triggered=cleared_count > 0,
            mode="clear_tools" if cleared_count else "none",
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            tool_results_cleared=cleared_count,
        )

    head = non_system[:-keep_tail]
    tail = non_system[-keep_tail:]
    summary, summary_mode = _summarize_block(
        head, llm_config, max_chars=max(1200, token_budget * 3 // 6)
    )
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
    # 压缩后消息已变，必须重新计算；复用该结果用于日志，避免重复编码。
    after_tokens = estimate_messages_tokens(compacted)
    if after_tokens > token_budget:
        truncated = _truncate_fallback(system_msgs, tail, max_tokens=token_budget)
        trunc_tokens = estimate_messages_tokens(truncated)
        logger.info(
            "compacted agent context via truncate: %s -> %s tokens",
            before_tokens,
            trunc_tokens,
        )
        return CompactionResult(
            messages=truncated,
            triggered=True,
            mode="truncate",
            before_tokens=before_tokens,
            after_tokens=trunc_tokens,
            tool_results_cleared=cleared_count,
            truncated=True,
        )
    logger.info(
        "compacted agent context: %s -> %s tokens (mode=%s)",
        before_tokens,
        after_tokens,
        summary_mode,
    )
    return CompactionResult(
        messages=compacted,
        triggered=True,
        mode=summary_mode,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        tool_results_cleared=cleared_count,
    )


def _summarize_block(
    messages: list[dict[str, Any]],
    llm_config: LlmConfig | None,
    *,
    max_chars: int,
) -> tuple[str, CompactionMode]:
    if llm_config is not None:
        body = _format_messages_for_summary(messages)
        if body.strip():
            # 按 token 截断输入，避免按字符截断时对 CJK 内容估计偏差。
            # 8000 token 约等于 24000 字符的英文内容。
            body = _truncate_text_by_tokens(body, max_tokens=8000, char_fallback=24_000)
            try:
                summary = chat_completion(
                    llm_config,
                    [
                        {
                            "role": "system",
                            "content": _COMPACT_SYSTEM.format(max_chars=max_chars),
                        },
                        {"role": "user", "content": body},
                    ],
                    temperature=0.0,
                    timeout=45.0,
                ).strip()
                if summary and len(summary) <= max_chars * 1.2:
                    return summary[:max_chars], "llm_summary"
            except AgentError as exc:
                logger.warning("LLM context compaction skipped: %s", exc)
    return _rule_summary(messages, max_chars=max_chars), "rule_summary"


def _truncate_text_by_tokens(
    text: str, *, max_tokens: int, char_fallback: int
) -> str:
    """截断文本到 max_tokens 个 token；tiktoken 不可用时回退到按字符截断。"""
    encoder = _get_tiktoken_encoder()
    if encoder is None:
        return text[:char_fallback]
    tokens = encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return str(encoder.decode(tokens[:max_tokens]))


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
    max_tokens: int,
) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = list(system_msgs)
    compacted.append(
        {
            "role": "user",
            "content": "[System] Earlier context truncated due to size limits.",
        }
    )
    used = estimate_messages_tokens(compacted)
    # Convert token budget to char budget for per-message trimming (heuristic).
    char_budget = max(200, (max_tokens - used) * _CHARS_PER_TOKEN_FALLBACK)
    for message in tail:
        content = message.get("content")
        if isinstance(content, str) and len(content) > char_budget // max(len(tail), 1):
            trimmed = dict(message)
            trimmed["content"] = content[: max(200, char_budget // max(len(tail), 1))] + "\n…[truncated]"
            compacted.append(trimmed)
        else:
            compacted.append(message)
    return compacted
