"""Memory and session search tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolResult
from secretary.memory.lumina_memory import LuminaMemory


class SearchMemoryTool(Tool):
    name = "search_memory"
    description = "Search local memory store for relevant information."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        }

    def __init__(self, store: Any) -> None:
        self._store = store

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        query = arguments.get("query", "")
        limit = arguments.get("limit", 5)
        chunks = self._store.search(query, limit=limit)
        if not chunks:
            return "No results found."
        lines = []
        for i, chunk in enumerate(chunks, 1):
            snippet = chunk.content[:300].replace("\n", " ")
            lines.append(f"{i}. [{chunk.source.value}] {chunk.title}\n   {snippet}")
        return "\n".join(lines)


class MemoryTool(Tool):
    name = "memory"
    description = (
        "Manage durable cross-session memory. "
        "target=memory edits MEMORY.md (environment/project facts); "
        "target=user edits USER.md (preferences/profile). "
        "Actions: add, replace (requires old_text), remove (requires old_text)."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = False

    def __init__(self, memory: LuminaMemory) -> None:
        self._memory = memory

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove"],
                    "description": "Memory operation",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "memory=MEMORY.md, user=USER.md",
                },
                "text": {"type": "string", "description": "Text to add or replacement text"},
                "old_text": {
                    "type": "string",
                    "description": "Substring to replace or remove (required for replace/remove)",
                },
            },
            "required": ["action", "target"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        try:
            return self._memory.mutate_memory(
                str(arguments.get("action", "")),
                str(arguments.get("target", "")),
                text=str(arguments.get("text", "")),
                old_text=str(arguments.get("old_text", "")),
            )
        except ValueError as exc:
            return ToolResult.failure(
                f"Error: {exc}",
                error_type="validation",
                retryable=False,
            )


class SessionSearchTool(Tool):
    name = "session_search"
    description = "Search past conversation sessions for relevant messages."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def __init__(self, memory: LuminaMemory) -> None:
        self._memory = memory

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 8)"},
            },
            "required": ["query"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult.failure(
                "Error: empty query",
                error_type="validation",
                retryable=False,
            )
        limit = int(arguments.get("limit", 8))
        results = self._memory.search_sessions(query, limit=limit)
        if not results:
            return "No matching session messages found."
        lines: list[str] = []
        for index, item in enumerate(results, start=1):
            role = item["role"]
            snippet = item["content"].replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "…"
            lines.append(
                f"{index}. [{item['session_id']}] {role} @ {item['timestamp']}\n   {snippet}"
            )
        return "\n".join(lines)
