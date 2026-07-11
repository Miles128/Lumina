"""Auto-refresh chat thread titles as the conversation deepens."""

from __future__ import annotations

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError

# Refresh after these user-turn counts (1 = first exchange done).
TITLE_REFRESH_AT_TURNS: frozenset[int] = frozenset({1, 3, 6, 12, 20})
MAX_TITLE_CHARS = 24

_TITLE_SYSTEM = """你是对话标题生成器。根据对话内容写一个简短中文标题。
要求：
- 最多 16 个汉字或 24 个字符
- 概括主题，不要照抄整句用户原话
- 不要引号、句号、书名号、emoji
- 不要以「关于」「请问」开头
- 只输出标题本身"""


def heuristic_title(user_message: str, *, max_chars: int = MAX_TITLE_CHARS) -> str:
    compact = " ".join(str(user_message or "").split()).strip()
    if not compact:
        return "新对话"
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1] + "…"


def user_turn_count(messages: list[dict[str, object]]) -> int:
    count = 0
    for item in messages:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "user":
            count += 1
    return count


def should_refresh_title(
    *,
    user_turns: int,
    last_auto_title_turn: int,
    refresh_at: frozenset[int] = TITLE_REFRESH_AT_TURNS,
) -> bool:
    if user_turns <= 0:
        return False
    if user_turns in refresh_at and user_turns > last_auto_title_turn:
        return True
    return False


def sanitize_title(raw: str, *, max_chars: int = MAX_TITLE_CHARS) -> str:
    text = str(raw or "").strip()
    text = text.strip("「」『』\"'“”‘’。．.！？!?")
    text = " ".join(text.split())
    if text.startswith("关于"):
        text = text[2:].lstrip(" ：:")
    if not text:
        return ""
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def summarize_thread_title(
    messages: list[dict[str, object]],
    llm_config: LlmConfig | None,
    *,
    fallback: str = "新对话",
) -> str:
    """Return a short title; falls back to heuristic/first user message on failure."""
    snippets: list[str] = []
    for item in messages[-12:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text") or item.get("content")
        if role not in {"user", "assistant", "bot"} or not isinstance(text, str):
            continue
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            continue
        label = "用户" if role == "user" else "助手"
        snippets.append(f"{label}: {cleaned[:160]}")
    if not snippets:
        return fallback

    first_user = next(
        (
            " ".join(str(item.get("text") or item.get("content") or "").split()).strip()
            for item in messages
            if isinstance(item, dict) and item.get("role") == "user"
        ),
        "",
    )
    heuristic = heuristic_title(first_user) if first_user else fallback

    if llm_config is None:
        return heuristic

    prompt = "\n".join(snippets)
    try:
        raw = chat_completion(
            llm_config,
            [
                {"role": "system", "content": _TITLE_SYSTEM},
                {"role": "user", "content": f"请为以下对话生成标题：\n\n{prompt}"},
            ],
            temperature=0.2,
            timeout=30.0,
        )
    except (AgentError, OSError, RuntimeError, TimeoutError, TypeError, ValueError):
        return heuristic

    cleaned = sanitize_title(raw)
    return cleaned or heuristic
