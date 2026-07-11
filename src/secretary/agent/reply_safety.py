"""User-facing reply safety and tone normalization."""

from __future__ import annotations

import re

from secretary.agent.reply_safety_rules import (
    load_forbidden_term_replacements,
    load_meta_reply_patterns,
    load_profanity_patterns,
    load_unprofessional_patterns,
)

_UNPROFESSIONAL_REPLACEMENT = "我这次判断失误"


def is_third_person_meta_reply(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    return any(pattern.search(cleaned) for pattern in load_meta_reply_patterns())


def contains_profanity(text: str) -> bool:
    """True when any configured profanity pattern matches."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in load_profanity_patterns())


def strip_reasoning_chain(text: str) -> str:
    """Remove model reasoning / chain-of-thought blocks from user-facing text."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"<\s*redacted_reasoning\s*>[\s\S]*?<\s*/\s*redacted_reasoning\s*>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*#{1,3}\s*思考(过程|链)?\s*\n+",
        "",
        cleaned,
        flags=re.MULTILINE,
    )
    return cleaned.strip()


def sanitize_user_facing_reply(reply: str, user_message: str) -> str:
    """Apply deterministic safety passes (meta / forbidden labels / tone).

    Profanity is intentionally not masked here — callers must run
    ``rewrite_profanity_until_clean`` (via ``prepare_user_facing_reply``)
    first when an LLM is available.
    """
    output = strip_reasoning_chain(reply)
    if is_third_person_meta_reply(output):
        output = (
            f"抱歉，刚才那句不对。\n"
            f"你说的「{user_message}」我听见了。\n"
            f"我重新来：你要我做什么，直接说，我按你的原话办。"
        )
    output = _sanitize_forbidden_terms(output)
    output = _sanitize_unprofessional_tone(output)
    return output


def _sanitize_forbidden_terms(text: str) -> str:
    cleaned = text
    for src, dst in load_forbidden_term_replacements():
        cleaned = cleaned.replace(src, dst)
    return cleaned


def _sanitize_unprofessional_tone(text: str) -> str:
    cleaned = text
    for pattern in load_unprofessional_patterns():
        cleaned = pattern.sub(_UNPROFESSIONAL_REPLACEMENT, cleaned)
    return cleaned
