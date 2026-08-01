"""Tests for builtin MCP registry (connector providers retired)."""
from __future__ import annotations

from secretary.agent.mcp_builtin import (
    BuiltinMcpProvider,
    BuiltinMcpRegistry,
    BuiltinToolSpec,
    build_builtin_registry,
)


class _FakeProvider(BuiltinMcpProvider):
    name = "fake"
    display_name = "测试源"

    def status(self) -> dict:
        return {"configured": True, "message": "ok", "item_count": 5}

    def tools(self) -> list[BuiltinToolSpec]:
        return [
            BuiltinToolSpec(
                tool_name="status",
                description="fake status",
                input_schema={"type": "object", "properties": {}},
                handler=lambda args: {"ok": True},
            ),
        ]


def test_registry_register_and_list():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    providers = reg.list_providers()
    assert len(providers) == 1
    assert providers[0].name == "fake"


def test_registry_get_tools_namespaced():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    tools = reg.get_tools()
    assert len(tools) == 1
    assert tools[0].full_name == "mcp_fake_status"


def test_registry_call_tool():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    result = reg.call_tool("mcp_fake_status", {})
    assert result == {"ok": True}


def test_registry_unknown_tool_returns_error():
    reg = BuiltinMcpRegistry()
    reg.register(_FakeProvider())
    result = reg.call_tool("mcp_fake_nonexistent", {})
    assert "error" in result


def test_builtin_registry_is_empty_after_connector_retirement():
    reg = build_builtin_registry(settings=None, sync_service=None)
    assert reg.list_providers() == []
    assert reg.get_tools() == []
