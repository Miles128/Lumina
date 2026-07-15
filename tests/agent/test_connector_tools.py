"""Tests for connector sync tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from secretary.agent.mcp_builtin import (
    BuiltinMcpProvider,
    BuiltinMcpRegistry,
    BuiltinToolSpec,
)
from secretary.agent.tools.connector_tools import (
    ConnectorStatusTool,
    ListConnectorsTool,
    SyncSourceTool,
    parse_source_kind,
)
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
from secretary.services.sync import SyncResult


def test_parse_source_kind_aliases() -> None:
    assert parse_source_kind("feishu") is SourceKind.FEISHU
    assert parse_source_kind("all") is None


def test_list_connectors_tool() -> None:
    sync = MagicMock()
    sync.get_stored_health.return_value = [
        ConnectorHealth(
            source=SourceKind.FEISHU,
            status=ConnectorStatus.READY,
            message="ok",
            item_count=3,
        )
    ]
    output = ListConnectorsTool(sync_service=sync).execute({}, Path("."))
    assert "feishu" in output
    assert "飞书" in output


def test_sync_source_tool_all() -> None:
    sync = MagicMock()
    sync.sync_all.return_value = [
        SyncResult(
            source=SourceKind.LOCAL_DOCUMENTS,
            inserted=2,
            health=ConnectorHealth(
                source=SourceKind.LOCAL_DOCUMENTS,
                status=ConnectorStatus.READY,
                message="done",
                item_count=2,
            ),
        )
    ]
    output = SyncSourceTool(sync).execute({"source": "all"}, Path("."))
    assert "写入 2 条" in output
    sync.sync_all.assert_called_once_with(include_browser_sources=False)


def test_connector_status_unknown_source() -> None:
    sync = MagicMock()
    output = ConnectorStatusTool(sync_service=sync).execute({"source": "unknown"}, Path("."))
    assert output.error and output.error.startswith("Error:")


# ---------------------------------------------------------------------------
# New tests for MCP builtin provider integration (Task 2.1)
# ---------------------------------------------------------------------------


class _FakeProvider(BuiltinMcpProvider):
    """Fake provider for testing — exposes status + fetch tools."""

    def __init__(self, name: str, display_name: str, status_payload: dict) -> None:
        self.name = name
        self.display_name = display_name
        self._status_payload = status_payload

    def status(self) -> dict:
        return self._status_payload

    def tools(self) -> list[BuiltinToolSpec]:
        return [
            BuiltinToolSpec(
                tool_name="status",
                description=f"{self.display_name} 状态",
                input_schema={"type": "object", "properties": {}},
                handler=lambda args: self._status_payload,
            ),
            BuiltinToolSpec(
                tool_name="fetch",
                description=f"拉取 {self.display_name}",
                input_schema={"type": "object", "properties": {}},
                handler=lambda args: {
                    "source": self.name,
                    "count": 1,
                    "chunks": [
                        {
                            "chunk_id": f"{self.name}-1",
                            "source": self.name,
                            "title": f"{self.display_name} 测试",
                            "content": "content",
                            "metadata": {},
                        }
                    ],
                },
            ),
        ]


def _build_registry_with_providers() -> BuiltinMcpRegistry:
    reg = BuiltinMcpRegistry()
    reg.register(
        _FakeProvider(
            "feishu",
            "飞书",
            {"configured": True, "status": "ready", "message": "ok", "item_count": 5},
        )
    )
    reg.register(
        _FakeProvider(
            "email",
            "邮箱",
            {"configured": False, "status": "not_configured", "message": "未配置", "item_count": 0},
        )
    )
    return reg


def test_list_connectors_reads_mcp_providers() -> None:
    """ListConnectorsTool should list providers from BuiltinMcpRegistry."""
    reg = _build_registry_with_providers()
    tool = ListConnectorsTool(registry=reg)
    result = tool.execute({}, Path("/tmp"))
    assert isinstance(result, str)
    assert "飞书" in result
    assert "邮箱" in result
    assert "feishu" in result
    assert "email" in result


def test_list_connectors_registry_empty() -> None:
    """Empty registry should return a friendly message."""
    reg = BuiltinMcpRegistry()
    tool = ListConnectorsTool(registry=reg)
    result = tool.execute({}, Path("/tmp"))
    assert isinstance(result, str)
    assert "暂无" in result or "无" in result


def test_connector_status_reads_mcp_provider() -> None:
    """ConnectorStatusTool should query single provider status via registry."""
    reg = _build_registry_with_providers()
    tool = ConnectorStatusTool(registry=reg)
    result = tool.execute({"source": "feishu"}, Path("/tmp"))
    assert isinstance(result, str)
    assert "飞书" in result
    assert "ready" in result or "ok" in result


def test_connector_status_unknown_source_via_registry() -> None:
    """Unknown source should return a structured failure."""
    reg = _build_registry_with_providers()
    tool = ConnectorStatusTool(registry=reg)
    result = tool.execute({"source": "unknown"}, Path("/tmp"))
    assert hasattr(result, "error")
    assert result.error is not None


def test_sync_source_tool_calls_mcp_fetch(monkeypatch) -> None:
    """SyncSourceTool should call mcp_manager.call_tool with mcp_{source}_fetch."""
    reg = _build_registry_with_providers()
    mcp_manager = MagicMock()
    # Simulate builtin fetch returning chunk payload.
    mcp_manager.call_tool.return_value = {
        "source": "feishu",
        "count": 1,
        "chunks": [
            {
                "chunk_id": "feishu-1",
                "source": "feishu",
                "title": "测试日程",
                "content": "content",
                "metadata": {},
            }
        ],
    }
    # Make _builtin.has_tool return True so SyncService-like paths work.
    mcp_manager._builtin = reg

    tool = SyncSourceTool(mcp_manager=mcp_manager)
    result = tool.execute({"source": "feishu"}, Path("/tmp"))
    # Tool should have called mcp_manager.call_tool with the namespaced fetch name.
    called_names = [call.args[0] for call in mcp_manager.call_tool.call_args_list]
    assert any("mcp_feishu_fetch" in str(name) for name in called_names)
    assert isinstance(result, str)
    assert "feishu" in result or "同步" in result


def test_sync_source_tool_falls_back_to_sync_service() -> None:
    """When mcp_manager is unavailable, SyncSourceTool should still use sync_service."""
    sync = MagicMock()
    sync.sync_source.return_value = SyncResult(
        source=SourceKind.FEISHU,
        inserted=3,
        health=ConnectorHealth(
            source=SourceKind.FEISHU,
            status=ConnectorStatus.READY,
            message="ok",
            item_count=3,
        ),
    )
    tool = SyncSourceTool(sync_service=sync)
    result = tool.execute({"source": "feishu"}, Path("/tmp"))
    sync.sync_source.assert_called_once_with(SourceKind.FEISHU)
    assert isinstance(result, str)
    assert "feishu" in result or "飞书" in result
