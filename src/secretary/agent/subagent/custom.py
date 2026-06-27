"""Load optional ~/.lumina/subagents/*.md archetype definitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from secretary.agent.subagent.policy import EXPLORE_MAX_STEPS

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SCALAR = re.compile(r"^([A-Za-z0-9_-]+):\s*(.+?)\s*$", re.MULTILINE)

_ALLOWED_CUSTOM_TOOLS = frozenset(
    {
        "list_dir",
        "file_read",
        "search_files",
        "search_memory",
        "session_search",
        "web_search",
        "web_fetch",
    }
)


@dataclass(frozen=True)
class CustomArchetypeSpec:
    name: str
    max_steps: int
    system_prompt: str
    tool_names: frozenset[str]
    mode: str = "subagent"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for key, value in _SCALAR.findall(match.group(1)):
        meta[key.strip().lower()] = value.strip()
    body = text[match.end() :].strip()
    return meta, body


def load_custom_archetypes(subagents_dir: Path) -> dict[str, CustomArchetypeSpec]:
    if not subagents_dir.is_dir():
        return {}
    specs: dict[str, CustomArchetypeSpec] = {}
    for path in sorted(subagents_dir.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(raw)
        name = (meta.get("name") or path.stem).strip().lower()
        if not name or not body:
            continue
        mode = (meta.get("mode") or "subagent").strip().lower()
        if mode == "primary":
            continue
        if name in {"explore", "worker", "verify", "plan"}:
            continue
        tool_names = _parse_tool_names(meta.get("tools", ""))
        if not tool_names:
            tool_names = frozenset({"list_dir", "file_read", "search_files"})
        max_steps = _parse_max_steps(meta.get("max_steps", ""))
        specs[name] = CustomArchetypeSpec(
            name=name,
            max_steps=max_steps,
            system_prompt=body,
            tool_names=tool_names,
            mode=mode,
        )
    return specs


def _parse_tool_names(raw: str) -> frozenset[str]:
    names = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return frozenset(n for n in names if n in _ALLOWED_CUSTOM_TOOLS)


def _parse_max_steps(raw: str) -> int:
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return EXPLORE_MAX_STEPS
    return max(1, min(value, 16))

