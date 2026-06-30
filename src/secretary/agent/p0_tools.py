"""Lumina P0 tools: search_files, patch, todo, skills, clarify."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from secretary.agent.skills import SkillManager
from secretary.agent.tools.base import Tool, _resolve_path
from secretary.services.todo_store import TodoStore

CLARIFY_PREFIX = "CLARIFY_REQUEST"
SEARCH_MAX_MATCHES = 50
SEARCH_MAX_LINE_CHARS = 300


class SearchFilesTool(Tool):
    name = "search_files"
    description = "Search file contents with ripgrep (or grep fallback). Returns matching paths and lines."
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex or plain text pattern"},
                "path": {"type": "string", "description": "Directory or file to search (default: working dir)"},
                "glob": {"type": "string", "description": "Optional glob filter, e.g. *.py"},
            },
            "required": ["pattern"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        pattern = str(arguments.get("pattern", "")).strip()
        if not pattern:
            return "Error: empty pattern"
        root = _resolve_path(str(arguments.get("path", ".")), working_dir)
        glob_filter = str(arguments.get("glob", "")).strip()
        if shutil.which("rg"):
            return self._search_rg(pattern, root, glob_filter)
        return self._search_grep(pattern, root)

    def _search_rg(self, pattern: str, root: Path, glob_filter: str) -> str:
        args = [
            "rg",
            "--json",
            "-m",
            str(SEARCH_MAX_MATCHES),
            pattern,
            str(root),
        ]
        if glob_filter:
            args[1:1] = ["--glob", glob_filter]
        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return "Error: search timed out"
        except OSError as exc:
            return f"Error: {exc}"
        if completed.returncode not in (0, 1):
            return completed.stderr.strip() or "Error: ripgrep failed"
        lines: list[str] = []
        for raw_line in completed.stdout.splitlines():
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "match":
                continue
            data = payload.get("data", {})
            path = data.get("path", {}).get("text", "")
            line_number = data.get("line_number", "")
            text = data.get("lines", {}).get("text", "").strip()
            if len(text) > SEARCH_MAX_LINE_CHARS:
                text = text[:SEARCH_MAX_LINE_CHARS] + "…"
            lines.append(f"{path}:{line_number}: {text}")
            if len(lines) >= SEARCH_MAX_MATCHES:
                break
        if not lines:
            return "No matches found."
        return "\n".join(lines)

    def _search_grep(self, pattern: str, root: Path) -> str:
        try:
            completed = subprocess.run(
                ["grep", "-R", "-n", "-I", "-m", str(SEARCH_MAX_MATCHES), pattern, str(root)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return f"Error: {exc}"
        output = completed.stdout.strip()
        if not output:
            return "No matches found."
        return output


class PatchTool(Tool):
    name = "patch"
    description = (
        "Replace exact text in a file (old_text -> new_text). "
        "Use for precise edits. Requires confirmation when modifying existing files."
    )
    needs_confirmation = False
    risk_level = "medium"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_text": {"type": "string", "description": "Exact text to replace (empty to create file)"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "new_text"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        if path.exists():
            return f"📝 修改文件 `{path}`（精确替换）"
        return f"📝 新建文件 `{path}`"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        old_text = str(arguments.get("old_text", ""))
        new_text = str(arguments.get("new_text", ""))
        if not path.exists():
            if old_text:
                return f"Error: file not found: {path}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
            return f"OK: created {path} ({len(new_text)} chars)"
        content = path.read_text(encoding="utf-8", errors="replace")
        if not old_text:
            return "Error: old_text required when patching existing file"
        if old_text not in content:
            return "Error: old_text not found in file"
        updated = content.replace(old_text, new_text, 1)
        path.write_text(updated, encoding="utf-8")
        return f"OK: patched {path}"


class TodoTool(Tool):
    name = "todo"
    description = "Manage the in-session task list: list, add, complete, remove, clear_done."
    needs_confirmation = False
    risk_level = "low"

    def __init__(self, store: TodoStore) -> None:
        self._store = store

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "complete", "remove", "clear_done"],
                },
                "content": {"type": "string", "description": "Todo text for add"},
                "id": {"type": "string", "description": "Todo id for complete/remove"},
            },
            "required": ["action"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        if action == "list":
            items = self._store.list_items()
            if not items:
                return "No todos."
            lines = []
            for item in items:
                mark = "x" if item.done else " "
                lines.append(f"[{mark}] {item.id}: {item.content}")
            return "\n".join(lines)
        if action == "add":
            item = self._store.add(str(arguments.get("content", "")))
            return f"Added todo {item.id}: {item.content}"
        if action == "complete":
            item = self._store.complete(str(arguments.get("id", "")).strip())
            return f"Completed {item.id}"
        if action == "remove":
            self._store.remove(str(arguments.get("id", "")).strip())
            return "Removed todo"
        if action == "clear_done":
            count = self._store.clear_done()
            return f"Cleared {count} completed todos"
        return f"Error: unknown action {action}"


class SkillsListTool(Tool):
    name = "skills_list"
    description = "List installed skills and available skill catalog entries."
    needs_confirmation = False
    risk_level = "low"

    def __init__(self, skills: SkillManager) -> None:
        self._skills = skills

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["installed", "catalog", "all"],
                    "description": "Which skills to list (default: installed)",
                },
                "source": {"type": "string", "description": "Optional catalog source filter"},
            },
            "required": [],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        scope = str(arguments.get("scope", "installed")).strip().lower() or "installed"
        source = str(arguments.get("source", "")).strip() or None
        lines: list[str] = []
        if scope in {"installed", "all"}:
            installed = self._skills.list_installed()
            lines.append("## Installed")
            if not installed:
                lines.append("(none)")
            for item in installed[:30]:
                lines.append(f"- {item.name}: {item.description}")
        if scope in {"catalog", "all"}:
            catalog = self._skills.catalog(source_key=source)
            lines.append("## Catalog")
            for item in catalog[:40]:
                flag = "installed" if item.installed else "available"
                lines.append(f"- [{flag}] {item.name} ({item.source_label}): {item.description}")
        return "\n".join(lines)


class SkillViewTool(Tool):
    name = "skill_view"
    description = "Load full SKILL.md body for an installed skill by name."
    needs_confirmation = False
    risk_level = "low"

    def __init__(self, skills: SkillManager) -> None:
        self._skills = skills

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name"},
                "max_chars": {"type": "integer", "description": "Max characters (default 6000)"},
            },
            "required": ["name"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        name = str(arguments.get("name", "")).strip()
        if not name:
            return "Error: skill name required"
        max_chars = int(arguments.get("max_chars", 6000))
        try:
            body = self._skills.read_skill_body(name, max_chars=max_chars)
        except Exception as exc:
            return f"Error: {exc}"
        return f"# Skill: {name}\n\n{body}"


class ClarifyTool(Tool):
    name = "clarify"
    description = (
        "Ask the user clarifying questions before proceeding. "
        "Provide 1-4 concise questions."
    )
    needs_confirmation = False
    risk_level = "low"

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Questions to ask the user",
                },
                "context": {"type": "string", "description": "Optional context for why asking"},
            },
            "required": ["questions"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        raw = arguments.get("questions", [])
        if not isinstance(raw, list):
            return "Error: questions must be a list"
        questions = [str(item).strip() for item in raw if str(item).strip()]
        if not questions:
            return "Error: at least one question required"
        context = str(arguments.get("context", "")).strip()
        lines = [CLARIFY_PREFIX]
        if context:
            lines.append(context)
        for index, question in enumerate(questions[:4], start=1):
            lines.append(f"{index}. {question}")
        return "\n".join(lines)


def is_clarify_output(text: str) -> bool:
    return text.strip().startswith(CLARIFY_PREFIX)
