"""Tests for MCP config store."""

from __future__ import annotations

from secretary.services.mcp_config import McpConfigDocument, McpConfigStore, McpServerConfig


def test_mcp_config_roundtrip(tmp_path) -> None:
    path = tmp_path / "mcp.json"
    store = McpConfigStore(path)
    store.save(
        McpConfigDocument(
            import_hermes=False,
            servers={
                "demo": McpServerConfig(
                    command="echo",
                    args=["hello"],
                    enabled=True,
                )
            },
        )
    )
    loaded = store.load()
    assert loaded.servers["demo"].command == "echo"
    assert store.list_view()[0]["name"] == "demo"


def test_mcp_upsert_and_import(tmp_path, monkeypatch) -> None:
    path = tmp_path / "mcp.json"
    store = McpConfigStore(path)
    store.upsert_server(
        "demo",
        McpServerConfig(command="npx", args=["-y", "pkg"], enabled=True),
    )
    persisted = store.load_persisted()
    assert "demo" in persisted.servers

    monkeypatch.setattr(
        "secretary.services.mcp_config._load_hermes_servers",
        lambda: {
            "hermes_demo": McpServerConfig(command="echo", args=["hi"], enabled=True),
        },
    )
    added = store.import_from_hermes()
    assert added == 1
    merged = store.load_persisted()
    assert "hermes_demo" in merged.servers
