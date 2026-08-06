"""Collect previewable artifact paths from tool calls for the sidebar."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import _resolve_path
from secretary.agent.tools.fs import EDIT_TOOL_NAMES, MOVE_TOOL_NAMES, WRITE_TOOL_NAMES

PREVIEW_EXTS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".csv",
        ".tsv",
        ".xlsx",
        ".xlsm",
        ".pdf",
        ".docx",
        ".html",
        ".htm",
        ".yaml",
        ".yml",
        ".py",
        ".js",
        ".ts",
        ".log",
    }
)

_ABS_FILE_RE = re.compile(
    r"(?:^|[\s`'\"(=])"
    r"("
    r"~?/?(?:Users|home|tmp|var|opt)/[^\s`'\"<>|;,&)]+"
    r"|/[^\s`'\"<>|;,&)]+\.[A-Za-z0-9]{1,8}"
    r")"
)


def _is_previewable(path: Path) -> bool:
    return path.suffix.lower() in PREVIEW_EXTS


def _normalize(path: Path) -> str | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    if not _is_previewable(resolved):
        return None
    return str(resolved)


def collect_artifact_paths(
    tool_name: str,
    arguments: dict[str, Any],
    working_dir: Path,
    *,
    output: str = "",
    success: bool = True,
) -> list[str]:
    """Return absolute paths that the UI should open in the artifact panel."""
    if not success:
        return []
    name = (tool_name or "").strip()
    found: list[str] = []

    if name in WRITE_TOOL_NAMES or name in EDIT_TOOL_NAMES:
        raw = str(arguments.get("path") or arguments.get("file_path") or "")
        if raw:
            norm = _normalize(_resolve_path(raw, working_dir))
            if norm:
                found.append(norm)
    elif name in MOVE_TOOL_NAMES:
        raw = str(arguments.get("to_path") or "")
        if raw:
            norm = _normalize(_resolve_path(raw, working_dir))
            if norm:
                found.append(norm)
    elif name in {"shell", "code_exec"}:
        text = f"{output}\n{arguments.get('command', '')}\n{arguments.get('code', '')}"
        for match in _ABS_FILE_RE.finditer(text):
            raw = match.group(1).rstrip(")]},.")
            try:
                candidate = Path(raw).expanduser()
                if not candidate.is_absolute():
                    candidate = working_dir / candidate
                norm = _normalize(candidate)
                if norm:
                    found.append(norm)
            except (OSError, ValueError):
                continue
        # Relative previewable names mentioned in backticks
        for match in re.finditer(r"`([^`\n]+\.[A-Za-z0-9]{1,8})`", text):
            raw = match.group(1).strip()
            if "/" not in raw and "\\" not in raw:
                norm = _normalize(working_dir / raw)
                if norm:
                    found.append(norm)

    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
