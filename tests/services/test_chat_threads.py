"""Tests for persistent chat thread store."""

from __future__ import annotations

from pathlib import Path

from secretary.services.chat_threads import ChatThreadStore


def test_thread_store_roundtrip(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(
        current_id="t_a",
        threads=[
            {
                "id": "t_a",
                "title": "Hello",
                "updatedAt": "2026-05-30T10:00:00+00:00",
                "messages": [{"role": "user", "text": "hi"}],
            }
        ],
    )
    view = store.list_view()
    assert view["current_id"] == "t_a"
    assert len(view["threads"]) == 1
    history = store.agent_history("t_a")
    assert history == [{"role": "user", "content": "hi"}]


def test_thread_store_append_turn(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t_b", threads=[])
    store.append_turn("t_b", "question", "answer")
    history = store.agent_history("t_b")
    assert history == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
