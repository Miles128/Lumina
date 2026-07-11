"""Load reply-safety filter rules from docs/reply-safety/*.md."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_RULES_DIR = Path(__file__).resolve().parents[3] / "docs" / "reply-safety"
_FENCE_RE = re.compile(
    r"```(?P<lang>regex|text)(?P<flags>[^\n]*)\n(?P<body>.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def rules_dir() -> Path:
    return _RULES_DIR


@lru_cache(maxsize=1)
def load_profanity_patterns() -> tuple[re.Pattern[str], ...]:
    return _compile_regex_file("profanity.md")


@lru_cache(maxsize=1)
def load_unprofessional_patterns() -> tuple[re.Pattern[str], ...]:
    return _compile_regex_file("unprofessional.md")


@lru_cache(maxsize=1)
def load_meta_reply_patterns() -> tuple[re.Pattern[str], ...]:
    return _compile_regex_file("meta-reply.md")


@lru_cache(maxsize=1)
def load_forbidden_term_replacements() -> tuple[tuple[str, str], ...]:
    path = _RULES_DIR / "forbidden-terms.md"
    if not path.is_file():
        return (("用户", "你"),)
    pairs: list[tuple[str, str]] = []
    for lang, _flags, body in _iter_fences(path.read_text(encoding="utf-8")):
        if lang != "text":
            continue
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "->" not in stripped:
                continue
            left, right = stripped.split("->", 1)
            src, dst = left.strip(), right.strip()
            if src and dst:
                pairs.append((src, dst))
    return tuple(pairs) if pairs else (("用户", "你"),)


def _compile_regex_file(filename: str) -> tuple[re.Pattern[str], ...]:
    path = _RULES_DIR / filename
    if not path.is_file():
        return ()
    compiled: list[re.Pattern[str]] = []
    for lang, flags_raw, body in _iter_fences(path.read_text(encoding="utf-8")):
        if lang != "regex":
            continue
        flags = re.IGNORECASE if "ignorecase" in flags_raw.lower() else 0
        for line in body.splitlines():
            pattern = line.strip()
            if not pattern or pattern.startswith("#"):
                continue
            compiled.append(re.compile(pattern, flags))
    return tuple(compiled)


def _iter_fences(text: str) -> list[tuple[str, str, str]]:
    return [
        (match.group("lang").lower(), match.group("flags") or "", match.group("body"))
        for match in _FENCE_RE.finditer(text)
    ]
