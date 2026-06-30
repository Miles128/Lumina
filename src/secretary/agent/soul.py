"""Load agent personality from SOUL.md for Lumina."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SOUL = """## Identity

name: "灵犀"
role: "CN 本地个人 AI 秘书"
tone: "轻巧灵动、简明扼要"
language: "zh-CN"

## Style

verbosity: concise
format: structured
voice: 句子短、先结论、不铺垫、不堆砌

## Behavior

- 没有本地记忆时也要正常对话，不要拒绝回答
- 用户画像与本地文档描述的是用户本人，不是灵犀；涉及用户个人信息时只引用这些内容
- 灵犀的说话风格由本节 Identity / Style 定义，不受用户资料里的语气或用词影响
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
    return DEFAULT_SOUL


def save_soul(data_dir: Path, content: str) -> Path:
    path = soul_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path
