"""HTTP tests for GET/PUT /api/agent/policy (isolated temp stores)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.services.agent_config import AgentConfigStore
from secretary.services.file_auth import FileAuthService


def _swap_policy_stores(tmp_path: Path) -> tuple[AgentConfigStore, FileAuthService]:
    store = AgentConfigStore(tmp_path / "agent.json")
    auth = FileAuthService(tmp_path / "auth.json")
    app.state.agent_config_store = store
    app.state.file_auth = auth
    return store, auth


def test_get_agent_policy_includes_permission_fields(tmp_path: Path) -> None:
    client = TestClient(app)
    _swap_policy_stores(tmp_path)
    response = client.get("/api/agent/policy")
    assert response.status_code == 200
    body = response.json()
    assert body["max_spawn_depth"] == 1
    assert body["permission_mode"] == "normal"
    assert body["require_confirm"]["write_modify"] is True
    assert body["editable"] is True


def test_put_agent_policy_auto_mode(tmp_path: Path) -> None:
    client = TestClient(app)
    store, auth = _swap_policy_stores(tmp_path)
    response = client.put(
        "/api/agent/policy",
        json={"permission_mode": "auto"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["permission_mode"] == "auto"
    assert body["require_confirm"]["write_new"] is False
    assert body["require_confirm"]["write_modify"] is True
    assert body["require_confirm"]["action"] is False
    assert body["session_grants"]["session_write_new"] is True
    assert body["session_grants"]["session_code_exec"] is True
    assert store.load().harness.permission_mode == "auto"
    assert auth.has_session_write_new() is True


def test_put_agent_policy_custom_kinds(tmp_path: Path) -> None:
    client = TestClient(app)
    _swap_policy_stores(tmp_path)
    response = client.put(
        "/api/agent/policy",
        json={
            "require_confirm": {
                "write_new": False,
                "write_modify": True,
                "write_delete": True,
                "shell": False,
                "action": True,
            },
            "session_grants": {
                "permanent_read": False,
                "session_write_new": True,
                "session_code_exec": False,
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["permission_mode"] == "custom"
    assert body["require_confirm"]["shell"] is False
    assert body["session_grants"]["session_write_new"] is True
    assert body["session_grants"]["session_code_exec"] is False
