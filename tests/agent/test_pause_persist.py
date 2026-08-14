"""Tests for confirmation pause persistence and restart restore."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.session_store import SessionStore


def test_session_store_upgrades_legacy_single_kind(tmp_path: Path) -> None:
    path = tmp_path / "turns.json"
    path.write_text(
        """{
  "turns": {},
  "pauses": {
    "legacy": {
      "kind": "confirmation",
      "data": {
        "pending": {
          "action_id": "a",
          "tool_name": "shell",
          "arguments": {},
          "description": "x",
          "risk_level": "high",
          "confirmation_kind": "shell"
        },
        "messages": []
      }
    }
  }
}
""",
        encoding="utf-8",
    )
    store = SessionStore(persistence_path=path)
    entry = store.load_pauses("legacy")
    assert set(entry) == {"confirmation"}
    assert entry["confirmation"]["pending"]["tool_name"] == "shell"


def test_confirmation_pause_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "turns.json"
    store = SessionStore(persistence_path=path)
    store.save_pause(
        "trace-m",
        kind="confirmation",
        data={
            "pending": {
                "action_id": "act_1",
                "tool_name": "shell",
                "arguments": {"command": "echo hi"},
                "description": "run",
                "risk_level": "high",
                "confirmation_kind": "shell",
            },
            "messages": [{"role": "user", "content": "run"}],
        },
    )

    reloaded = SessionStore(persistence_path=path)
    entry = reloaded.load_pauses("trace-m")
    assert set(entry) == {"confirmation"}
    assert entry["confirmation"]["pending"]["tool_name"] == "shell"
