"""Connector sync tools exposed to the agent (P0).

The three tools (``list_connectors`` / ``connector_status`` / ``sync_source``)
are thin orchestration wrappers over the MCP builtin provider registry and
``SyncService``. Tool names are preserved so existing agent prompts do not
need to change; only the underlying data source shifts from direct connector
access to MCP provider metadata.

Backwards compatibility:

- ``ListConnectorsTool`` / ``ConnectorStatusTool`` accept a
  ``BuiltinMcpRegistry`` as the primary dependency (``registry=``). When the
  registry is unavailable, they fall back to ``sync_service`` so legacy call
  sites keep working.
- ``SyncSourceTool`` keeps ``sync_service`` as the first positional argument
  and adds an optional ``mcp_manager``. When only ``mcp_manager`` is supplied
  the tool calls ``mcp_{source}_fetch`` directly; otherwise it delegates to
  ``sync_service.sync_source`` which already routes through MCP internally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolResult
from secretary.core.types import SOURCE_LABELS, ConnectorStatus, SourceKind
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

_STATUS_VALUE_MAP: dict[str, ConnectorStatus] = {
    "ready": ConnectorStatus.READY,
    "error": ConnectorStatus.ERROR,
    "not_configured": ConnectorStatus.NOT_CONFIGURED,
}


def parse_source_kind(raw: str) -> SourceKind | None:
    normalized = raw.strip().lower().replace("-", "_")
    if not normalized or normalized == "all":
        return None
    return _SOURCE_ALIASES.get(normalized)


def _parse_status_value(raw: Any) -> ConnectorStatus:
    if isinstance(raw, ConnectorStatus):
        return raw
    if isinstance(raw, str):
        return _STATUS_VALUE_MAP.get(raw.strip().lower(), ConnectorStatus.READY)
    return ConnectorStatus.READY


def _parse_last_sync_at(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _format_health(
    source: SourceKind,
    status: ConnectorStatus,
    message: str,
    *,
    inserted: int = 0,
    last_sync_at: datetime | None = None,
    item_count: int = 0,
) -> str:
    label = SOURCE_LABELS.get(source, source.value)
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


def _format_provider_status(
    source: SourceKind,
    display_name: str,
    status_payload: dict[str, Any],
    *,
    inserted: int = 0,
) -> str:
    """Render an MCP provider status dict in the same shape as ``_format_health``."""
    label = display_name or SOURCE_LABELS.get(source, source.value)
    status_value = _parse_status_value(status_payload.get("status"))
    message = str(status_payload.get("message", "") or "")
    item_count = int(status_payload.get("item_count", 0) or 0)
    last_sync_at = _parse_last_sync_at(status_payload.get("last_sync_at"))
    sync_at = last_sync_at.astimezone(UTC).isoformat() if last_sync_at else "从未"
    lines = [
        f"- **{label}** (`{source.value}`)",
        f"  状态: {status_value.value}",
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

    def __init__(
        self,
        registry: Any | None = None,
        *,
        sync_service: SyncService | None = None,
    ) -> None:
        self._registry = registry
        self._sync_service = sync_service

    def _parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "查看连接器状态"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        if self._registry is not None:
            return self._execute_via_registry()
        if self._sync_service is not None:
            return self._execute_via_sync_service()
        return "暂无已注册的连接器。"

    def _execute_via_registry(self) -> str | ToolResult:
        providers = self._registry.list_providers()
        if not providers:
            return "暂无已注册的连接器。"
        blocks: list[str] = []
        for provider in providers:
            source = _SOURCE_ALIASES.get(provider.name)
            if source is None:
                continue
            status_payload = self._registry.call_tool(
                f"mcp_{provider.name}_status", {}
            )
            if isinstance(status_payload, dict) and "error" in status_payload:
                blocks.append(
                    _format_provider_status(
                        source,
                        provider.display_name,
                        {"status": "error", "message": status_payload["error"]},
                    )
                )
                continue
            blocks.append(
                _format_provider_status(
                    source, provider.display_name, status_payload or {}
                )
            )
        if not blocks:
            return "暂无已注册的连接器。"
        return "## 连接器\n\n" + "\n\n".join(blocks)

    def _execute_via_sync_service(self) -> str | ToolResult:
        health = self._sync_service.get_stored_health()
        if not health:
            return "暂无已注册的连接器。"
        blocks = [
            _format_health(
                item.source,
                item.status,
                item.message,
                item_count=item.item_count,
                last_sync_at=item.last_sync_at,
            )
            for item in health
        ]
        return "## 连接器\n\n" + "\n\n".join(blocks)


class ConnectorStatusTool(Tool):
    name = "connector_status"
    description = "Get sync status for one connector source (read-only)."
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def __init__(
        self,
        registry: Any | None = None,
        *,
        sync_service: SyncService | None = None,
    ) -> None:
        self._registry = registry
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
        if self._registry is not None and self._registry.has_tool(
            f"mcp_{source.value}_status"
        ):
            return self._execute_via_registry(source)
        return self._execute_via_sync_service(source)

    def _execute_via_registry(self, source: SourceKind) -> str | ToolResult:
        provider = next(
            (p for p in self._registry.list_providers() if p.name == source.value),
            None,
        )
        if provider is None:
            return ToolResult.failure(
                f"Error: source {source.value} not found",
                error_type="not_found",
                retryable=False,
            )
        status_payload = self._registry.call_tool(f"mcp_{source.value}_status", {})
        if isinstance(status_payload, dict) and "error" in status_payload:
            return ToolResult.failure(
                status_payload["error"],
                error_type="builtin_error",
                retryable=False,
            )
        return _format_provider_status(
            source, provider.display_name, status_payload or {}
        )

    def _execute_via_sync_service(self, source: SourceKind) -> str | ToolResult:
        if self._sync_service is None:
            return ToolResult.failure(
                "Error: no registry or sync_service available",
                error_type="internal",
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

    def __init__(
        self,
        sync_service: SyncService | None = None,
        *,
        mcp_manager: Any | None = None,
    ) -> None:
        self._sync_service = sync_service
        self._mcp_manager = mcp_manager

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
            return self._sync_all(include_browser)

        source = parse_source_kind(raw)
        if source is None:
            known = ", ".join(["all", *sorted(_SOURCE_ALIASES)])
            return ToolResult.failure(
                f"Error: unknown source. Known: {known}",
                error_type="validation",
                retryable=False,
            )
        return self._sync_one(source)

    def _sync_all(self, include_browser: bool) -> str | ToolResult:
        if self._sync_service is None:
            return ToolResult.failure(
                "Error: sync_service unavailable — cannot sync all sources",
                error_type="internal",
                retryable=False,
            )
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

    def _sync_one(self, source: SourceKind) -> str | ToolResult:
        # Preferred path: SyncService already routes through MCP internally.
        if self._sync_service is not None:
            result = self._sync_service.sync_source(source)
            return _format_health(
                result.source,
                result.health.status,
                result.health.message,
                inserted=result.inserted,
                item_count=result.health.item_count,
                last_sync_at=result.health.last_sync_at,
            )
        # Fallback: call the builtin MCP fetch tool directly and report counts.
        if self._mcp_manager is None:
            return ToolResult.failure(
                "Error: no sync_service or mcp_manager available",
                error_type="internal",
                retryable=False,
            )
        full_name = f"mcp_{source.value}_fetch"
        if not (
            hasattr(self._mcp_manager, "_builtin")
            and self._mcp_manager._builtin.has_tool(full_name)
        ):
            return ToolResult.failure(
                f"Error: source {source.value} not available via MCP",
                error_type="not_found",
                retryable=False,
            )
        raw = self._mcp_manager.call_tool(full_name, {})
        if isinstance(raw, dict) and "error" in raw:
            return ToolResult.failure(
                raw["error"],
                error_type="builtin_error",
                retryable=False,
            )
        chunks = raw.get("chunks", []) if isinstance(raw, dict) else []
        count = int(raw.get("count", len(chunks))) if isinstance(raw, dict) else len(chunks)
        provider_display = self._provider_display_name(source)
        return _format_provider_status(
            source,
            provider_display,
            {
                "status": "ready",
                "message": f"通过 MCP 拉取 {count} 条",
                "item_count": count,
                "last_sync_at": datetime.now(UTC).isoformat(),
            },
            inserted=count,
        )

    def _provider_display_name(self, source: SourceKind) -> str:
        if self._mcp_manager is None:
            return SOURCE_LABELS.get(source, source.value)
        builtin = getattr(self._mcp_manager, "_builtin", None)
        if builtin is None:
            return SOURCE_LABELS.get(source, source.value)
        for provider in builtin.list_providers():
            if provider.name == source.value:
                return provider.display_name
        return SOURCE_LABELS.get(source, source.value)
