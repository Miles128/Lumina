"""Lumina P0 tools: search_files, glob_files, patch, todo, skills, clarify, ask_user."""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from secretary.agent.skills import SkillManager
from secretary.agent.tools.base import Tool, ToolResult, _resolve_path
from secretary.services.todo_store import TodoStore

CLARIFY_PREFIX = "CLARIFY_REQUEST"
ASK_USER_PREFIX = "ASK_USER_REQUEST"
SEARCH_MAX_MATCHES = 50
SEARCH_MAX_LINE_CHARS = 300
GLOB_MAX_RESULTS = 200


class SearchFilesTool(Tool):
    name = "search_files"
    description = "Search file contents with ripgrep (or grep fallback). Returns matching paths and lines."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        pattern = str(arguments.get("pattern", "")).strip()
        if not pattern:
            return ToolResult.failure(
                "Error: empty pattern",
                error_type="validation",
                retryable=False,
            )
        root = _resolve_path(str(arguments.get("path", ".")), working_dir)
        glob_filter = str(arguments.get("glob", "")).strip()
        if shutil.which("rg"):
            return self._search_rg(pattern, root, glob_filter)
        return self._search_grep(pattern, root)

    def _search_rg(self, pattern: str, root: Path, glob_filter: str) -> str | ToolResult:
        args = [
            "rg",
            "--json",
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
            return ToolResult.failure(
                "Error: search timed out",
                error_type="timeout",
                retryable=True,
            )
        except OSError as exc:
            return ToolResult.failure(
                f"Error: {exc}",
                error_type="internal",
                retryable=False,
            )
        if completed.returncode not in (0, 1):
            return ToolResult.failure(
                completed.stderr.strip() or "Error: ripgrep failed",
                error_type="internal",
                retryable=False,
            )
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

    def _search_grep(self, pattern: str, root: Path) -> str | ToolResult:
        try:
            completed = subprocess.run(
                ["grep", "-R", "-n", "-I", "-m", str(SEARCH_MAX_MATCHES), pattern, str(root)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure(
                "Error: search timed out",
                error_type="timeout",
                retryable=True,
            )
        except OSError as exc:
            return ToolResult.failure(
                f"Error: {exc}",
                error_type="internal",
                retryable=False,
            )
        output = completed.stdout.strip()
        if not output:
            return "No matches found."
        return output


class GlobFilesTool(Tool):
    name = "glob_files"
    description = (
        "Find files by glob pattern (e.g. **/*.py, src/**/*.ts). "
        "Use for locating files by name/path, not content search."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. **/*.md"},
                "path": {"type": "string", "description": "Root directory (default: working dir)"},
            },
            "required": ["pattern"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        pattern = str(arguments.get("pattern", "")).strip()
        if not pattern:
            return ToolResult.failure(
                "Error: empty pattern",
                error_type="validation",
                retryable=False,
            )
        root = _resolve_path(str(arguments.get("path", ".")), working_dir)
        if not root.exists():
            return ToolResult.failure(
                f"Error: path not found: {root}",
                error_type="not_found",
                retryable=False,
            )
        if not root.is_dir():
            return ToolResult.failure(
                f"Error: not a directory: {root}",
                error_type="not_found",
                retryable=False,
            )
        try:
            all_matches = sorted(
                path for path in root.glob(pattern) if path.is_file()
            )
        except ValueError as exc:
            return ToolResult.failure(
                f"Error: invalid glob pattern ({exc})",
                error_type="validation",
                retryable=False,
            )
        total = len(all_matches)
        matches = all_matches[:GLOB_MAX_RESULTS]
        if not matches:
            return "No files matched."
        lines = []
        for path in matches:
            try:
                lines.append(str(path.relative_to(root)))
            except ValueError:
                lines.append(str(path))
        suffix = f"\n...(truncated at {GLOB_MAX_RESULTS})" if total > GLOB_MAX_RESULTS else ""
        return "\n".join(lines) + suffix


class PatchTool(Tool):
    name = "patch"
    description = (
        "Replace exact text in a file (old_text -> new_text). Only the first match is replaced. "
        "Use for precise edits. Requires confirmation when modifying existing files."
    )
    needs_confirmation = False
    risk_level = "medium"
    read_only = False

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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        path = _resolve_path(str(arguments.get("path", "")), working_dir)
        old_text = str(arguments.get("old_text", ""))
        new_text = str(arguments.get("new_text", ""))
        if not path.exists():
            if old_text:
                return ToolResult.failure(
                    f"Error: file not found: {path}",
                    error_type="not_found",
                    retryable=False,
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
            return f"OK: created {path} ({len(new_text)} chars)"
        content = path.read_text(encoding="utf-8", errors="replace")
        if not old_text:
            return ToolResult.failure(
                "Error: old_text required when patching existing file",
                error_type="validation",
                retryable=False,
            )
        if old_text not in content:
            return ToolResult.failure(
                "Error: old_text not found in file",
                error_type="validation",
                retryable=False,
            )
        updated = content.replace(old_text, new_text, 1)
        path.write_text(updated, encoding="utf-8")
        return f"OK: patched {path}"


class TodoTool(Tool):
    name = "todo"
    description = "Manage the in-session task list: list, add, complete, remove, clear_done."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
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
        return ToolResult.failure(
            f"Error: unknown action {action}",
            error_type="validation",
            retryable=False,
        )


class NotesTool(Tool):
    """Read or update the persistent notes file (~/.lumina/NOTES.md).

    Notes persist across sessions and survive context compaction.
    Use them to record key decisions, file paths, and unresolved issues.
    """

    name = "notes"
    description = "Read or update persistent notes (NOTES.md). Actions: read, append, replace."
    needs_confirmation = False
    risk_level = "low"
    read_only = False

    def __init__(self, notes_path: Path) -> None:
        self._path = notes_path

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "append", "replace"],
                    "description": "read: show notes; append: add to end; replace: overwrite all",
                },
                "content": {
                    "type": "string",
                    "description": "Text for append/replace",
                },
            },
            "required": ["action"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        action = str(arguments.get("action", "")).strip().lower()
        if action == "read":
            if self._path.exists():
                text = self._path.read_text(encoding="utf-8").strip()
                return text or "(notes file is empty)"
            return "(no notes yet)"
        if action == "append":
            content = str(arguments.get("content", "")).strip()
            if not content:
                return ToolResult.failure("Error: content is empty", error_type="validation")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch(exist_ok=True)
            with open(self._path, "r+", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                existing = f.read().rstrip()
                new_text = f"{existing}\n\n{content}" if existing else content
                f.seek(0)
                f.truncate()
                f.write(new_text + "\n")
            return f"Appended to notes ({len(content)} chars)"
        if action == "replace":
            content = str(arguments.get("content", "")).strip()
            if not content:
                return ToolResult.failure("Error: content is empty", error_type="validation")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.touch(exist_ok=True)
            with open(self._path, "r+", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.seek(0)
                f.truncate()
                f.write(content + "\n")
            return f"Replaced notes ({len(content)} chars)"
        return ToolResult.failure(
            f"Error: unknown action {action}",
            error_type="validation",
            retryable=False,
        )


class SkillsListTool(Tool):
    name = "skills_list"
    description = "List installed skills and available skill catalog entries."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
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
    read_only = True

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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        name = str(arguments.get("name", "")).strip()
        if not name:
            return ToolResult.failure(
                "Error: skill name required",
                error_type="validation",
                retryable=False,
            )
        max_chars = int(arguments.get("max_chars", 6000))
        try:
            body = self._skills.read_skill_body(name, max_chars=max_chars)
        except Exception as exc:
            return ToolResult.failure(
                f"Error: {exc}",
                error_type="internal",
                retryable=False,
            )
        return f"# Skill: {name}\n\n{body}"


class ClarifyTool(Tool):
    name = "clarify"
    description = (
        "Ask the user clarifying questions before proceeding. "
        "Provide 1-4 concise questions."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = True

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

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        raw = arguments.get("questions", [])
        if not isinstance(raw, list):
            return ToolResult.failure(
                "Error: questions must be a list",
                error_type="validation",
                retryable=False,
            )
        questions = [str(item).strip() for item in raw if str(item).strip()]
        if not questions:
            return ToolResult.failure(
                "Error: at least one question required",
                error_type="validation",
                retryable=False,
            )
        context = str(arguments.get("context", "")).strip()
        lines = [CLARIFY_PREFIX]
        if context:
            lines.append(context)
        for index, question in enumerate(questions[:4], start=1):
            lines.append(f"{index}. {question}")
        return "\n".join(lines)


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user structured questions with optional choices. "
        "Prefer over clarify when options are known. Stops the loop until the user replies."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "description": "1-4 structured questions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "prompt": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "allow_multiple": {"type": "boolean"},
                        },
                        "required": ["prompt"],
                    },
                },
                "context": {"type": "string", "description": "Optional intro shown above questions"},
            },
            "required": ["questions"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        raw = arguments.get("questions", [])
        if not isinstance(raw, list):
            return ToolResult.failure(
                "Error: questions must be a list",
                error_type="validation",
                retryable=False,
            )
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw[:4], start=1):
            if isinstance(item, str):
                prompt = item.strip()
                if prompt:
                    normalized.append({"id": f"q{index}", "prompt": prompt, "options": []})
                continue
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt", "")).strip()
            if not prompt:
                continue
            question_id = str(item.get("id", f"q{index}")).strip() or f"q{index}"
            options_raw = item.get("options", [])
            options = (
                [str(opt).strip() for opt in options_raw if str(opt).strip()]
                if isinstance(options_raw, list)
                else []
            )
            normalized.append(
                {
                    "id": question_id,
                    "prompt": prompt,
                    "options": options[:8],
                    "allow_multiple": bool(item.get("allow_multiple", False)),
                }
            )
        if not normalized:
            return ToolResult.failure(
                "Error: at least one question required",
                error_type="validation",
                retryable=False,
            )
        payload = {
            "version": 1,
            "context": str(arguments.get("context", "")).strip(),
            "questions": normalized,
        }
        return ASK_USER_PREFIX + "\n" + json.dumps(payload, ensure_ascii=False)


def is_clarify_output(text: str) -> bool:
    return text.strip().startswith(CLARIFY_PREFIX)


def is_ask_user_output(text: str) -> bool:
    return text.strip().startswith(ASK_USER_PREFIX)


def is_user_input_request(text: str) -> bool:
    return is_clarify_output(text) or is_ask_user_output(text)


def format_user_input_reply(tool_output: str, *, thought: str) -> str:
    if is_ask_user_output(tool_output):
        return tool_output.strip()
    if "\n" in tool_output:
        return tool_output.split("\n", 1)[1].strip()
    return thought
