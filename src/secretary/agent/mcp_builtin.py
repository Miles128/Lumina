"""Builtin MCP providers — connectors exposed as in-process MCP tools.

Each connector (feishu/email/weread/...) is wrapped as a BuiltinMcpProvider,
registered in BuiltinMcpRegistry, and exposed via McpManager under the
unified namespace ``mcp_{provider}_{tool}`` — identical to remote/stdio MCP
servers. SyncService calls ``mcp_{source}_fetch`` to pull chunks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class BuiltinToolSpec:
    """Declarative spec for a single builtin MCP tool."""

    tool_name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


class BuiltinMcpProvider(Protocol):
    """A connector exposed as a set of in-process MCP tools.

    Providers share the agent process (no subprocess), so they can read
    PlatformConfigStore directly. Tools are namespaced as ``mcp_{name}_{tool}``.
    """

    name: str
    display_name: str

    def status(self) -> dict[str, Any]:
        """Return configuration status: {configured, message, item_count, last_sync_at?}."""
        ...

    def tools(self) -> list[BuiltinToolSpec]:
        """Return tool specs exposed by this provider."""
        ...


@dataclass
class _RegisteredTool:
    provider_name: str
    tool_name: str
    full_name: str  # mcp_{provider}_{tool}
    spec: BuiltinToolSpec


class BuiltinMcpRegistry:
    """Registry of builtin MCP providers. McpManager reads from this."""

    def __init__(self) -> None:
        self._providers: dict[str, BuiltinMcpProvider] = {}
        self._tools: dict[str, _RegisteredTool] = {}

    def register(self, provider: BuiltinMcpProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Duplicate builtin provider: {provider.name}")
        self._providers[provider.name] = provider
        for spec in provider.tools():
            full_name = f"mcp_{provider.name}_{spec.tool_name}"
            self._tools[full_name] = _RegisteredTool(
                provider_name=provider.name,
                tool_name=spec.tool_name,
                full_name=full_name,
                spec=spec,
            )

    def list_providers(self) -> list[BuiltinMcpProvider]:
        return list(self._providers.values())

    def get_tools(self) -> list[_RegisteredTool]:
        return list(self._tools.values())

    def call_tool(self, full_name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(full_name)
        if tool is None:
            return {"error": f"Unknown builtin tool: {full_name}"}
        try:
            return tool.spec.handler(arguments)
        except Exception as exc:  # noqa: BLE001 — MCP tool error boundary
            return {"error": f"{type(exc).__name__}: {exc}"}

    def has_tool(self, full_name: str) -> bool:
        return full_name in self._tools


from secretary.connectors.feishu import FeishuConnector
from secretary.connectors.email_imap import EmailConnector
from secretary.connectors.weread import WeReadConnector
from secretary.connectors.xiaohongshu import XiaohongshuConnector
from secretary.connectors.weixin_oa import WeixinOAConnector
from secretary.connectors.cloud_drive import CloudDriveConnector
from secretary.core.types import SourceKind


class _ConnectorProvider:
    """Wrap a BaseConnector as a BuiltinMcpProvider exposing status + fetch."""

    def __init__(self, source: SourceKind, display_name: str, connector_factory: Callable) -> None:
        self.name = source.value
        self.display_name = display_name
        self._source = source
        self._connector_factory = connector_factory

    def _connector(self, settings: Any):
        return self._connector_factory(settings)

    def status(self) -> dict[str, Any]:
        # Read stored health from sync_service if available; else probe connector.
        # Implementation defers to SyncService.get_stored_health for read-only safety.
        raise NotImplementedError("wired in build_builtin_registry")

    def tools(self) -> list[BuiltinToolSpec]:
        return [
            BuiltinToolSpec(
                tool_name="status",
                description=f"{self.display_name} 连接器状态(只读)",
                input_schema={"type": "object", "properties": {}},
                handler=self._status_handler,
            ),
            BuiltinToolSpec(
                tool_name="fetch",
                description=f"拉取 {self.display_name} 数据,返回 list[MemoryChunk] JSON",
                input_schema={"type": "object", "properties": {}},
                handler=self._fetch_handler,
            ),
        ]

    def _status_handler(self, args: dict[str, Any]) -> Any:
        return self.status()

    def _fetch_handler(self, args: dict[str, Any]) -> Any:
        # Defer to the bound sync_service (injected at registry build time).
        raise NotImplementedError("wired in build_builtin_registry")


def build_builtin_registry(settings: Any, sync_service: Any) -> BuiltinMcpRegistry:
    """Build registry with all 6 connector providers.

    ``settings`` and ``sync_service`` are injected so providers can read config
    and trigger fetch without re-instantiating connectors themselves.
    """
    reg = BuiltinMcpRegistry()

    connector_specs = [
        (SourceKind.FEISHU, "飞书", FeishuConnector),
        (SourceKind.EMAIL, "邮箱", EmailConnector),
        (SourceKind.WEREAD, "微信读书", WeReadConnector),
        (SourceKind.XIAOHONGSHU, "小红书", XiaohongshuConnector),
        (SourceKind.WEIXIN_OA, "微信公众号", WeixinOAConnector),
        (SourceKind.CLOUD_DRIVE, "本地网盘目录", CloudDriveConnector),
    ]

    for source, display_name, factory in connector_specs:
        provider = _ConnectorProvider(source, display_name, factory)

        # Wire status: read from sync_service stored health (read-only, no CLI calls).
        def make_status(src: SourceKind):
            def _status(args):
                if sync_service is None:
                    return {"configured": False, "message": "sync service unavailable", "item_count": 0}
                for item in sync_service.get_stored_health():
                    if item.source is src:
                        return {
                            "configured": item.status.value != "not_configured",
                            "status": item.status.value,
                            "message": item.message,
                            "item_count": item.item_count,
                            "last_sync_at": item.last_sync_at.isoformat() if item.last_sync_at else None,
                        }
                return {"configured": False, "message": "未注册", "item_count": 0}
            return _status

        # Wire fetch: call connector.fetch() and serialize chunks to dict.
        def make_fetch(src: SourceKind, fctry):
            def _fetch(args):
                if settings is None:
                    return {"error": "settings unavailable"}
                connector = fctry(settings)
                if not connector.is_configured():
                    return {"error": f"{src.value} 未配置"}
                chunks = connector.fetch()
                return {
                    "source": src.value,
                    "count": len(chunks),
                    "chunks": [
                        {
                            "chunk_id": c.chunk_id,
                            "source": c.source.value,
                            "title": c.title,
                            "content": c.content,
                            "metadata": c.metadata,
                        }
                        for c in chunks
                    ],
                }
            return _fetch

        # Override provider handlers with wired closures.
        provider._status_handler = make_status(source)  # type: ignore[method-assign]
        provider._fetch_handler = make_fetch(source, factory)  # type: ignore[method-assign]
        reg.register(provider)

    return reg
