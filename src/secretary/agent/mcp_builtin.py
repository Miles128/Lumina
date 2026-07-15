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
