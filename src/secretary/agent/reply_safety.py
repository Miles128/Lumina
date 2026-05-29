"""User-facing reply safety and tone normalization."""

from __future__ import annotations

import re

_META_REPLY_PATTERNS = (
    re.compile(r"用户.{0,40}(未明确|情绪化|情绪激动|反问|指责|抱怨)"),
    re.compile(r"需等待用户"),
    re.compile(r"需要澄清.{0,20}用户"),
    re.compile(r"^用户[^。]{4,80}[。，]"),
)

_PROFANITY_PATTERNS = (
    re.compile(r"傻[逼屌吊叼比B]"),
    re.compile(r"[操艹草]你妈"),
    re.compile(r"他妈的"),
    re.compile(r"妈的"),
    re.compile(r"去死"),
    re.compile(r"垃圾"),
    re.compile(r"f\*?u\*?c\*?k", re.IGNORECASE),
    re.compile(r"shit", re.IGNORECASE),
)

_UNPROFESSIONAL_PATTERNS = (
    re.compile(r"我[眼]?瞎了"),
    re.compile(r"我太笨了"),
    re.compile(r"嘴硬"),
    re.compile(r"跟你犟"),
    re.compile(r"没别的原因"),
)

def is_third_person_meta_reply(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    return any(pattern.search(cleaned) for pattern in _META_REPLY_PATTERNS)


def sanitize_user_facing_reply(reply: str, user_message: str) -> str:
    output = reply.strip()
    if is_third_person_meta_reply(output):
        output = (
            f"抱歉，刚才那句不对。\n"
            f"你说的「{user_message}」我听见了。\n"
            f"我重新来：你要我做什么，直接说，我按你的原话办。"
        )
    output = _sanitize_profanity(output)
    output = _sanitize_forbidden_terms(output)
    output = _sanitize_unprofessional_tone(output)
    output = _ensure_gentle_tone(output, user_message)
    return output


def _sanitize_profanity(text: str) -> str:
    cleaned = text
    for pattern in _PROFANITY_PATTERNS:
        cleaned = pattern.sub("***", cleaned)
    return cleaned


def _sanitize_forbidden_terms(text: str) -> str:
    # Hard ban certain labels in user-facing replies.
    return text.replace("用户", "你")


def _sanitize_unprofessional_tone(text: str) -> str:
    cleaned = text
    for pattern in _UNPROFESSIONAL_PATTERNS:
        cleaned = pattern.sub("我这次判断失误", cleaned)
    return cleaned


def _ensure_gentle_tone(text: str, user_message: str) -> str:
    if not text:
        return ""
    return text
