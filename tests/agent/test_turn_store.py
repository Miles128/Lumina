"""Tests for session store disk persistence."""

from __future__ import annotations

from secretary.agent.session_store import SessionStore


def test_session_store_turn_roundtrip(tmp_path) -> None:
    path = tmp_path / "turns.json"
    session = SessionStore(persistence_path=path)
    turn = session.start_turn(trace_id="trace-1", thread_id="t1", user_message="hello")
    assert turn.turn_id.startswith("turn_")

    reloaded = SessionStore(persistence_path=path)
    loaded = reloaded.get_turn("trace-1")
    assert loaded is not None
    assert loaded.turn_id == turn.turn_id
    assert loaded.user_message == "hello"


def test_session_store_pause_bundle(tmp_path) -> None:
    path = tmp_path / "turns.json"
    store = SessionStore(persistence_path=path)
    store.save_pause(
        "trace-2",
        kind="confirmation",
        data={
            "pending": {
                "action_id": "act_1",
                "tool_name": "shell",
                "arguments": {"command": "echo hi"},
                "description": "run shell",
                "risk_level": "high",
                "confirmation_kind": "shell",
            },
            "messages": [{"role": "user", "content": "run echo"}],
        },
    )
    loaded = store.load_pause("trace-2")
    assert loaded is not None
    kind, data = loaded
    assert kind == "confirmation"
    assert data["pending"]["tool_name"] == "shell"


def test_session_store_clear_turn_removes_disk_record(tmp_path) -> None:
    path = tmp_path / "turns.json"
    session = SessionStore(persistence_path=path)
    session.start_turn(trace_id="trace-3", user_message="x")
    session.clear_turn("trace-3")
    assert SessionStore(persistence_path=path).get_turn("trace-3") is None
