"""Builtin in-process MCP providers — connector wrappers retired.

User-added MCP servers remain via McpManager. This registry stays empty so the
old connector bridge (飞书/微信读书/邮箱等) is no longer exposed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class BuiltinToolSpec:
    """Declarative spec for a single builtin MCP tool."""

    tool_name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


class BuiltinMcpProvider(Protocol):
    name: str
    display_name: str

    def status(self) -> dict[str, Any]:
        ...

    def tools(self) -> list[BuiltinToolSpec]:
        ...


@dataclass
class _RegisteredTool:
    provider_name: str
    tool_name: str
    full_name: str
    spec: BuiltinToolSpec


class BuiltinMcpRegistry:
    """Registry of builtin MCP providers. Empty after connector retirement."""

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


def build_builtin_registry(settings: Any, sync_service: Any) -> BuiltinMcpRegistry:
    """Return empty registry — standalone connector MCP providers removed."""
    del settings, sync_service
    return BuiltinMcpRegistry()
