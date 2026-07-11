"""LLM-based rewrite for machine-like third-person phrasing and profanity."""

from __future__ import annotations

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.agent.reply_safety import contains_profanity, sanitize_user_facing_reply
from secretary.agent.reply_safety_rules import load_forbidden_term_replacements
from secretary.exceptions import AgentError

_MAX_PROFANITY_REWRITE_ATTEMPTS = 5


def _forbidden_label() -> str:
    pairs = load_forbidden_term_replacements()
    return pairs[0][0] if pairs else "用户"


FORBIDDEN_LABEL = _forbidden_label()

_STRONG_REWRITE_MARKERS = (
    "未明确",
    "命令模糊",
    "指令模糊",
    "情绪化",
    "情绪激动",
    "需等待",
    "需要澄清",
    "第三人称",
)

_LITE_REWRITE_SYSTEM = f"""你是对话润色器。把一句机器腔文本改成自然对话。
要求：
1) 保持原意，不新增事实。
2) 直接对“你”说话。
3) 禁止出现“{FORBIDDEN_LABEL}”两个字。
4) 语气平稳、礼貌，不啰嗦。
5) 优先 1 句；必要时最多 2 句。
6) 只输出最终改写，不要解释。"""

_STRONG_REWRITE_SYSTEM = f"""你是对话修复器。把第三人称分析腔改写成可直接沟通的话。
要求：
1) 保持原意，不新增事实。
2) 去掉审稿口吻、评价口吻、情绪分析。
3) 全部改为对“你”的直接表达。
4) 禁止出现“{FORBIDDEN_LABEL}”两个字。
5) 语气平稳、温和、简短，不说套话。
6) 优先 1 句；必要时最多 2 句。
7) 只输出最终改写，不要解释。"""

_PROFANITY_REWRITE_SYSTEM = """你是对话润色器。下面这段回复含有脏话、粗口或不雅俚语。
要求：
1) 保持原意与事实，不新增内容，不删减关键信息。
2) 去掉所有脏话、粗口、骂人话，改成礼貌、自然的表达。
3) 不要用星号、谐音或「哔」遮盖；直接写成干净句子。
4) 直接对读者说话；只输出改写后的全文，不要解释。"""


def prepare_user_facing_reply(
    reply: str,
    user_message: str,
    llm_config: LlmConfig | None,
) -> str:
    """Single pipeline: LLM rewrites (forbidden label → profanity) then deterministic sanitize.

    Order matters: sanitize replaces forbidden labels, so LLM rewrite must run first.
    """
    text = rewrite_if_forbidden_label(reply, user_message, llm_config)
    text = rewrite_profanity_until_clean(text, user_message, llm_config)
    return sanitize_user_facing_reply(text, user_message)


def rewrite_if_forbidden_label(
    reply: str,
    user_message: str,
    llm_config: LlmConfig | None,
) -> str:
    text = reply.strip()
    if not text or FORBIDDEN_LABEL not in text or llm_config is None:
        return text
    return _llm_rewrite(
        text,
        user_message,
        llm_config,
        system_prompt=_pick_rewrite_system_prompt(text),
        user_prefix="请改写：",
    )


def rewrite_profanity_until_clean(
    reply: str,
    user_message: str,
    llm_config: LlmConfig | None,
    *,
    max_attempts: int = _MAX_PROFANITY_REWRITE_ATTEMPTS,
) -> str:
    """Ask the LLM to rewrite until no configured profanity pattern remains."""
    text = reply.strip()
    if not text or not contains_profanity(text):
        return text
    if llm_config is None:
        return text

    current = text
    attempts = max(1, max_attempts)
    for _ in range(attempts):
        if not contains_profanity(current):
            return current
        rewritten = _llm_rewrite(
            current,
            user_message,
            llm_config,
            system_prompt=_PROFANITY_REWRITE_SYSTEM,
            user_prefix="请改写为不含脏话的版本：",
        )
        if not rewritten or rewritten == current:
            break
        current = rewritten

    return current


def _llm_rewrite(
    text: str,
    user_message: str,
    llm_config: LlmConfig,
    *,
    system_prompt: str,
    user_prefix: str,
) -> str:
    try:
        rewritten = chat_completion(
            llm_config,
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"原句：{text}\n"
                        f"对话上下文（可参考）：{user_message}\n"
                        f"{user_prefix}"
                    ),
                },
            ],
            temperature=0.0,
            timeout=20.0,
        ).strip()
        return rewritten or text
    except AgentError:
        return text


def _pick_rewrite_system_prompt(text: str) -> str:
    hits = sum(marker in text for marker in _STRONG_REWRITE_MARKERS)
    if hits >= 1 or text.count(FORBIDDEN_LABEL) >= 2:
        return _STRONG_REWRITE_SYSTEM
    return _LITE_REWRITE_SYSTEM
