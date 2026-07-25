"""Pi-aligned unique text edit helpers (LF / BOM / light fuzzy)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EditApplyResult:
    ok: bool
    error: str | None = None
    used_fuzzy: bool = False


def detect_line_ending(content: str) -> str:
    crlf = content.find("\r\n")
    lf = content.find("\n")
    if lf == -1:
        return "\n"
    if crlf == -1:
        return "\n"
    return "\r\n" if crlf < lf else "\n"


def normalize_to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_line_endings(text: str, ending: str) -> str:
    if ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def strip_bom(content: str) -> tuple[str, str]:
    if content.startswith("\ufeff"):
        return "\ufeff", content[1:]
    return "", content


def normalize_for_fuzzy_match(text: str) -> str:
    lines = [line.rstrip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    normalized = (
        normalized.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201a", "'")
        .replace("\u201b", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u201e", '"')
        .replace("\u201f", '"')
    )
    normalized = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", normalized)
    normalized = re.sub(r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " ", normalized)
    return normalized


@dataclass(frozen=True)
class _Match:
    index: int
    match_length: int
    used_fuzzy: bool
    content_for_replacement: str


def fuzzy_find_text(content: str, old_text: str) -> _Match | None:
    exact = content.find(old_text)
    if exact != -1:
        return _Match(exact, len(old_text), False, content)
    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old = normalize_for_fuzzy_match(old_text)
    idx = fuzzy_content.find(fuzzy_old)
    if idx == -1:
        return None
    return _Match(idx, len(fuzzy_old), True, fuzzy_content)


def count_occurrences(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    return haystack.count(needle)


@dataclass(frozen=True)
class EditComputeResult:
    ok: bool
    final_text: str = ""
    used_fuzzy: bool = False
    error: str | None = None


def compute_unique_edit(path: Path, *, old_text: str, new_text: str) -> EditComputeResult:
    """Compute edited file text without writing (for confirm diff preview)."""
    if not path.exists() or not path.is_file():
        return EditComputeResult(ok=False, error=f"Error: file not found: {path}")
    if not old_text:
        return EditComputeResult(
            ok=False,
            error="Error: oldText required when editing an existing file (use write to create)",
        )
    raw = path.read_text(encoding="utf-8", errors="replace")
    bom, text = strip_bom(raw)
    ending = detect_line_ending(text)
    content = normalize_to_lf(text)
    old_n = normalize_to_lf(old_text)
    new_n = normalize_to_lf(new_text)

    match = fuzzy_find_text(content, old_n)
    if match is None:
        return EditComputeResult(
            ok=False,
            error=(
                f"Error: could not find the exact text in {path}. "
                "oldText must match including whitespace and newlines."
            ),
        )

    fuzzy_content = normalize_for_fuzzy_match(match.content_for_replacement)
    fuzzy_old = normalize_for_fuzzy_match(old_n)
    occurrences = count_occurrences(fuzzy_content, fuzzy_old)
    if occurrences > 1:
        return EditComputeResult(
            ok=False,
            error=(
                f"Error: found {occurrences} occurrences of the text in {path}. "
                "The text must be unique; provide more context."
            ),
        )

    base = match.content_for_replacement
    updated = (
        base[: match.index] + new_n + base[match.index + match.match_length :]
    )
    if updated == base:
        return EditComputeResult(
            ok=False,
            error=f"Error: no changes made to {path} (replacement identical).",
        )

    final = bom + restore_line_endings(updated, ending)
    return EditComputeResult(ok=True, final_text=final, used_fuzzy=match.used_fuzzy)


def apply_unique_edit(path: Path, *, old_text: str, new_text: str) -> EditApplyResult:
    computed = compute_unique_edit(path, old_text=old_text, new_text=new_text)
    if not computed.ok:
        return EditApplyResult(ok=False, error=computed.error)
    path.write_text(computed.final_text, encoding="utf-8")
    return EditApplyResult(ok=True, used_fuzzy=computed.used_fuzzy)


_DIFF_MAX_CHARS = 8_000
_DIFF_MAX_LINES = 200


def format_line_diff(before: str, after: str, *, path_label: str = "file") -> str:
    """Compact unified-style diff for confirmation UI (no difflib dependency)."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    lines = [f"--- a/{path_label}", f"+++ b/{path_label}"]
    # Simple LCS-free hunk: show removed then added when short; else truncate.
    if before_lines == after_lines:
        return ""
    max_ctx = _DIFF_MAX_LINES
    removed = [f"-{line}" for line in before_lines[:max_ctx]]
    added = [f"+{line}" for line in after_lines[:max_ctx]]
    if len(before_lines) > max_ctx:
        removed.append(f"-… ({len(before_lines) - max_ctx} more lines)")
    if len(after_lines) > max_ctx:
        added.append(f"+… ({len(after_lines) - max_ctx} more lines)")
    lines.extend(removed)
    lines.extend(added)
    text = "\n".join(lines)
    if len(text) > _DIFF_MAX_CHARS:
        return text[: _DIFF_MAX_CHARS - 20] + "\n… (diff truncated)"
    return text


def build_confirm_diff_preview(
    tool_name: str,
    arguments: dict,
    working_dir: Path,
) -> str:
    """Build a read-only diff preview for write/edit confirmations."""
    from secretary.agent.tools.base import _resolve_path
    from secretary.agent.tools.fs import EDIT_TOOL_NAMES, WRITE_TOOL_NAMES

    name = (tool_name or "").strip()
    if name in EDIT_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        old_text = str(
            arguments.get("oldText")
            if arguments.get("oldText") is not None
            else arguments.get("old_text", "")
        )
        new_text = str(
            arguments.get("newText")
            if arguments.get("newText") is not None
            else arguments.get("new_text", "")
        )
        if not path.exists():
            return ""
        before = path.read_text(encoding="utf-8", errors="replace")
        computed = compute_unique_edit(path, old_text=old_text, new_text=new_text)
        if not computed.ok:
            return f"(diff unavailable: {computed.error})"
        return format_line_diff(before, computed.final_text, path_label=path.name)

    if name in WRITE_TOOL_NAMES:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        content_raw = arguments.get("content", "")
        content = content_raw if isinstance(content_raw, str) else str(content_raw)
        append = bool(arguments.get("append", False))
        label = path.name or "file"
        if append and path.exists():
            before = path.read_text(encoding="utf-8", errors="replace")
            return format_line_diff(before, before + content, path_label=label)
        if path.exists():
            before = path.read_text(encoding="utf-8", errors="replace")
            return format_line_diff(before, content, path_label=label)
        # New file: show additions only
        added = [f"+{line}" for line in content.splitlines()[:_DIFF_MAX_LINES]]
        if len(content.splitlines()) > _DIFF_MAX_LINES:
            added.append("+… (truncated)")
        text = "\n".join(["--- /dev/null", f"+++ b/{label}", *added])
        if len(text) > _DIFF_MAX_CHARS:
            return text[: _DIFF_MAX_CHARS - 20] + "\n… (diff truncated)"
        return text
    return ""
