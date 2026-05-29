"""Load agent personality from SOUL.md (Hermes-compatible)."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SOUL = """## Identity

name: "灵犀"
role: "CN 本地个人 AI 秘书"
tone: "直接、简洁、实用"
language: "zh-CN"

## Style

verbosity: concise
format: structured

## Behavior

- 没有本地记忆时也要正常对话，不要拒绝回答
- 个人相关信息优先引用画像和记忆；没有就说明并给出通用建议
- 不编造用户的个人信息
"""


def soul_path(data_dir: Path) -> Path:
    return data_dir / "SOUL.md"


def hermes_soul_path() -> Path:
    return Path.home() / ".hermes" / "SOUL.md"


def load_soul(data_dir: Path) -> str:
    local = soul_path(data_dir)
    if local.exists():
        text = local.read_text(encoding="utf-8").strip()
        if text:
            return text
    hermes = hermes_soul_path()
    if hermes.exists():
        text = hermes.read_text(encoding="utf-8").strip()
        if text:
            return text
    return DEFAULT_SOUL


def save_soul(data_dir: Path, content: str) -> Path:
    path = soul_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path
