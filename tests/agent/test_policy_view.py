"""FR-46 policy summary."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.policy_view import build_policy_view
from secretary.services.file_auth import FileAuthService


def test_build_policy_view_depth_and_archetypes(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "auth.json")
    auth.grant_session_write_new()
    view = build_policy_view(auth)
    assert view["max_spawn_depth"] == 1
    assert view["max_parallel_explore"] == 3
    names = {item["name"] for item in view["archetypes"]}
    assert "explore" in names
    assert "worker" in names
    assert "verify" in names
    worker = next(item for item in view["archetypes"] if item["name"] == "worker")
    assert worker["can_write"] is True
    assert worker["can_spawn"] is False
    explore = next(item for item in view["archetypes"] if item["name"] == "explore")
    assert explore["can_write"] is False
    assert view["session_grants"]["session_write_new"] is True
    assert any(p["id"] == "build" and p["can_spawn"] for p in view["profiles"])
    assert view["permission_mode"] == "normal"
    assert view["require_confirm"]["write_new"] is True
    assert view["editable"] is True
