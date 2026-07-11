"""Tests for connector sync tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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
    output = ListConnectorsTool(sync).execute({}, Path("."))
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
    output = ConnectorStatusTool(sync).execute({"source": "unknown"}, Path("."))
    assert output.error and output.error.startswith("Error:")
