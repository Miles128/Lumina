"""Agent tools backed by the Shibei semantic knowledge base."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolResult
from secretary.services.shibei_service import ShibeiService, format_list_sources


class ShibeiSearchTool(Tool):
    name = "shibei_search"
    description = (
        "Search Lumina's Shibei semantic knowledge base (indexed markdown/docs). "
        "Use for personal notes, articles, interview prep, and synced document Q&A. "
        "If results are empty, call shibei_import or guide the user to Settings → Shibei."
    )
    read_only = True

    def __init__(self, service: ShibeiService) -> None:
        self._service = service

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords or question"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
                "tag": {"type": "string", "description": "Optional tag filter"},
            },
            "required": ["query"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        query = str(arguments.get("query", "")).strip()
        return f"检索 Shibei 知识库：{query[:80]}" if query else "检索 Shibei 知识库"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        try:
            result = self._service.search(
                str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 5)),
                tag=str(arguments.get("tag", "")).strip() or None,
            )
            from secretary.services.shibei_service import is_shibei_empty_result

            if is_shibei_empty_result(result):
                return f"{result}\n\n[Agent hint] 可调用 shibei_import 增量导入，或让用户在设置 → Shibei 检查 sources。"
            return result
        except Exception as error:
            return ToolResult.failure(
                f"Error: {error}",
                error_type="internal",
                retryable=False,
            )


class ShibeiImportTool(Tool):
    name = "shibei_import"
    description = (
        "Incrementally import monitored folders into the Shibei knowledge base. "
        "Run after adding new documents or when search returns empty."
    )
    read_only = False

    def __init__(self, service: ShibeiService) -> None:
        self._service = service

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    "description": "Full rebuild instead of incremental import",
                }
            },
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "全量重建 Shibei 索引" if arguments.get("full") else "增量导入 Shibei 知识库"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        try:
            result = self._service.import_all(full=bool(arguments.get("full", False)))
            return result.message
        except Exception as error:
            return ToolResult.failure(
                f"Error: {error}",
                error_type="internal",
                retryable=False,
            )


class ShibeiListSourcesTool(Tool):
    name = "shibei_list_sources"
    description = "List documents currently indexed in the Shibei knowledge base."
    read_only = True

    def __init__(self, service: ShibeiService) -> None:
        self._service = service

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max entries (default 20)"},
                "offset": {"type": "integer", "description": "Pagination offset"},
            },
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "列出 Shibei 已索引文档"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        try:
            payload = self._service.list_sources(
                limit=int(arguments.get("limit", 20)),
                offset=int(arguments.get("offset", 0)),
            )
            return format_list_sources(payload)
        except Exception as error:
            return ToolResult.failure(
                f"Error: {error}",
                error_type="internal",
                retryable=False,
            )
