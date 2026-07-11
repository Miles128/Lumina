"""Connector sync tools exposed to the agent (P0)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolResult
from secretary.core.types import ConnectorStatus, SourceKind
from secretary.services.sync import SyncService

_SOURCE_ALIASES: dict[str, SourceKind] = {
    "feishu": SourceKind.FEISHU,
    "email": SourceKind.EMAIL,
    "weread": SourceKind.WEREAD,
    "xiaohongshu": SourceKind.XIAOHONGSHU,
    "weixin_oa": SourceKind.WEIXIN_OA,
    "cloud_drive": SourceKind.CLOUD_DRIVE,
    "local_documents": SourceKind.LOCAL_DOCUMENTS,
}

_SOURCE_LABELS: dict[SourceKind, str] = {
    SourceKind.FEISHU: "飞书",
    SourceKind.EMAIL: "邮箱",
    SourceKind.WEREAD: "微信读书",
    SourceKind.XIAOHONGSHU: "小红书",
    SourceKind.WEIXIN_OA: "微信公众号",
    SourceKind.CLOUD_DRIVE: "云盘",
    SourceKind.LOCAL_DOCUMENTS: "本地文档",
}


def parse_source_kind(raw: str) -> SourceKind | None:
    normalized = raw.strip().lower().replace("-", "_")
    if not normalized or normalized == "all":
        return None
    return _SOURCE_ALIASES.get(normalized)


def _format_health(source: SourceKind, status: ConnectorStatus, message: str, *, inserted: int = 0, last_sync_at: datetime | None = None, item_count: int = 0) -> str:
    label = _SOURCE_LABELS.get(source, source.value)
    sync_at = last_sync_at.astimezone(UTC).isoformat() if last_sync_at else "从未"
    lines = [
        f"- **{label}** (`{source.value}`)",
        f"  状态: {status.value}",
        f"  说明: {message or '—'}",
        f"  条目: {item_count}",
        f"  上次同步: {sync_at}",
    ]
    if inserted:
        lines.append(f"  本次写入: {inserted}")
    return "\n".join(lines)


class ListConnectorsTool(Tool):
    name = "list_connectors"
    description = (
        "List configured data connectors and their sync status. "
        "Use before sync_source or when the user asks about Feishu/WeRead/etc. data."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def __init__(self, sync_service: SyncService) -> None:
        self._sync_service = sync_service

    def _parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "查看连接器状态"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        health = self._sync_service.get_stored_health()
        if not health:
            return "暂无已注册的连接器。"
        blocks = [_format_health(item.source, item.status, item.message, item_count=item.item_count, last_sync_at=item.last_sync_at) for item in health]
        return "## 连接器\n\n" + "\n\n".join(blocks)


class ConnectorStatusTool(Tool):
    name = "connector_status"
    description = "Get sync status for one connector source (read-only)."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def __init__(self, sync_service: SyncService) -> None:
        self._sync_service = sync_service

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Connector id: feishu, email, weread, xiaohongshu, weixin_oa, "
                        "cloud_drive, local_documents"
                    ),
                },
            },
            "required": ["source"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        source = str(arguments.get("source", "")).strip()
        return f"查看连接器 {source or '状态'}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        source = parse_source_kind(str(arguments.get("source", "")))
        if source is None:
            known = ", ".join(sorted(_SOURCE_ALIASES))
            return ToolResult.failure(
                f"Error: unknown source. Known: {known}",
                error_type="validation",
                retryable=False,
            )
        for item in self._sync_service.get_stored_health():
            if item.source is source:
                return _format_health(
                    item.source,
                    item.status,
                    item.message,
                    item_count=item.item_count,
                    last_sync_at=item.last_sync_at,
                )
        return ToolResult.failure(
            f"Error: source {source.value} not found",
            error_type="not_found",
            retryable=False,
        )


class SyncSourceTool(Tool):
    name = "sync_source"
    description = (
        "Sync one connector or all connectors into Lumina memory. "
        "Use when the user asks to refresh Feishu/WeRead/local docs data."
    )
    needs_confirmation = True
    risk_level = "medium"
    read_only = False

    def __init__(self, sync_service: SyncService) -> None:
        self._sync_service = sync_service

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Connector id, or 'all' to sync every configured source",
                },
                "include_browser_sources": {
                    "type": "boolean",
                    "description": "Include WeRead/Xiaohongshu browser-backed sources (default false)",
                },
            },
            "required": ["source"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        source = str(arguments.get("source", "all")).strip() or "all"
        return f"同步数据源：{source}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        raw = str(arguments.get("source", "")).strip().lower()
        include_browser = bool(arguments.get("include_browser_sources", False))
        if raw in {"", "all"}:
            results = self._sync_service.sync_all(include_browser_sources=include_browser)
            if not results:
                return "没有可同步的连接器。"
            blocks = [
                _format_health(
                    item.source,
                    item.health.status,
                    item.health.message,
                    inserted=item.inserted,
                    item_count=item.health.item_count,
                    last_sync_at=item.health.last_sync_at,
                )
                for item in results
            ]
            total = sum(item.inserted for item in results)
            return f"同步完成，共写入 {total} 条。\n\n" + "\n\n".join(blocks)

        source = parse_source_kind(raw)
        if source is None:
            known = ", ".join(["all", *sorted(_SOURCE_ALIASES)])
            return ToolResult.failure(
                f"Error: unknown source. Known: {known}",
                error_type="validation",
                retryable=False,
            )
        result = self._sync_service.sync_source(source)
        return _format_health(
            result.source,
            result.health.status,
            result.health.message,
            inserted=result.inserted,
            item_count=result.health.item_count,
            last_sync_at=result.health.last_sync_at,
        )
