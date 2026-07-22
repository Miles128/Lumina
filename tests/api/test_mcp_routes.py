"""HTTP tests for MCP server mutate / reload routes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.services.mcp_config import McpConfigStore


def test_mcp_upsert_reload_and_delete(tmp_path: Path) -> None:
    client = TestClient(app)
    original_store = app.state.mcp_config_store
    original_reload = app.state.mcp_manager.reload
    temp_store = McpConfigStore(tmp_path / "mcp.json")
    reloads: list[int] = []

    def fake_reload() -> None:
        reloads.append(1)

    app.state.mcp_config_store = temp_store
    app.state.mcp_manager.reload = fake_reload  # type: ignore[method-assign]
    name = "p1_test_echo"
    try:
        listed = client.get("/api/mcp/servers")
        assert listed.status_code == 200
        assert listed.json()["servers"] == []

        created = client.post(
            "/api/mcp/servers",
            json={
                "name": name,
                "command": "echo",
                "args": ["ok"],
                "enabled": True,
            },
        )
        assert created.status_code == 200
        assert reloads
        names = {row["name"] for row in temp_store.list_view()}
        assert name in names

        reloaded = client.post("/api/mcp/reload")
        assert reloaded.status_code == 200
        assert len(reloads) >= 2

        deleted = client.delete(f"/api/mcp/servers/{name}")
        assert deleted.status_code == 200
        assert name not in {row["name"] for row in temp_store.list_view()}

        missing = client.delete(f"/api/mcp/servers/{name}")
        assert missing.status_code == 404
    finally:
        app.state.mcp_config_store = original_store
        app.state.mcp_manager.reload = original_reload  # type: ignore[method-assign]
