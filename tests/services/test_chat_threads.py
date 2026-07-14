"""Tests for persistent chat thread store."""

from __future__ import annotations

import json
from pathlib import Path

from secretary.services.chat_threads import (
    MAX_HISTORY_MESSAGES,
    MAX_THREAD_MESSAGES,
    ChatThreadStore,
)


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


def test_append_assistant_message_skips_missing_thread_and_preserves_title(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    created = store.create_thread(title="新对话")
    thread_id = str(created["current_id"])
    store.append_turn(thread_id, "hello", "world")

    assert store.append_assistant_message("missing", "好的，已取消操作。") is False
    assert store.append_assistant_message(thread_id, "好的，已取消操作。") is True

    thread = next(t for t in store.list_view()["threads"] if t["id"] == thread_id)
    assert thread["title"] != "system"
    assert thread["messages"][-1]["role"] == "assistant"
    assert thread["messages"][-1]["text"] == "好的，已取消操作。"
    assert not any(m.get("text") == "system" for m in thread["messages"])


def test_thread_store_create_set_current_and_delete(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")

    created = store.create_thread(title="Planning")
    thread_id = created["current_id"]
    assert thread_id
    assert created["threads"][0]["title"] == "Planning"

    second = store.create_thread()
    second_id = second["current_id"]
    assert second_id != thread_id

    switched = store.set_current(thread_id)
    assert switched["current_id"] == thread_id

    deleted = store.delete_thread(thread_id)
    assert deleted["current_id"] == second_id
    assert all(item["id"] != thread_id for item in deleted["threads"])


def test_thread_store_delete_last_creates_replacement(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    created = store.create_thread()

    deleted = store.delete_thread(str(created["current_id"]))

    assert deleted["current_id"]
    assert len(deleted["threads"]) == 1
    assert deleted["threads"][0]["messages"] == []


def test_append_turn_sets_heuristic_title_only_once(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    created = store.create_thread(title="新对话")
    thread_id = str(created["current_id"])
    store.append_turn(thread_id, "帮我整理下周飞书会议", "好的")
    title1 = store.list_view()["threads"][0]["title"]
    assert "飞书" in title1 or "会议" in title1
    store.append_turn(thread_id, "再加一个周五站会", "已记下")
    title2 = store.list_view()["threads"][0]["title"]
    assert title2 == title1


def test_maybe_refresh_title_at_milestone(tmp_path: Path) -> None:
    from unittest.mock import patch

    from secretary.agent.llm_config import LlmConfig

    store = ChatThreadStore(tmp_path / "chat_threads.json")
    created = store.create_thread(title="新对话")
    thread_id = str(created["current_id"])
    store.append_turn(thread_id, "帮我整理下周飞书会议", "下周有三场会")
    cfg = LlmConfig(api_key="k", base_url="https://example.com/v1", model="m", source="env")
    with patch(
        "secretary.services.thread_title.chat_completion",
        return_value="飞书下周会议",
    ):
        updated = store.maybe_refresh_title(thread_id, llm_config=cfg)
    assert updated == "飞书下周会议"
    assert store.list_view()["threads"][0]["title"] == "飞书下周会议"
    assert store.list_view()["threads"][0]["auto_title_at_turn"] == 1


# --- Tree branching tests (Task 1/2/9 data layer) ---


def test_load_migrates_flat_messages(tmp_path: Path) -> None:
    path = tmp_path / "chat_threads.json"
    raw = {
        "current_id": "t_old",
        "threads": [
            {
                "id": "t_old",
                "title": "Old",
                "messages": [
                    {"role": "user", "text": "q1"},
                    {"role": "assistant", "text": "a1"},
                    {"role": "user", "text": "q2"},
                ],
            }
        ],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    store = ChatThreadStore(path)
    view = store.list_view()
    thread = view["threads"][0]
    msgs = thread["messages"]
    assert len(msgs) == 3

    assert msgs[0]["id"].startswith("m_")
    assert msgs[0]["parent_id"] == ""
    assert msgs[1]["parent_id"] == msgs[0]["id"]
    assert msgs[2]["parent_id"] == msgs[1]["id"]
    assert thread["active_leaf_id"] == msgs[2]["id"]
    for m in msgs:
        assert m["archived"] is False

    # migration persisted to disk and ids are stable on reload
    raw2 = json.loads(path.read_text(encoding="utf-8"))
    persisted_ids = [m["id"] for m in raw2["threads"][0]["messages"]]
    assert persisted_ids == [m["id"] for m in msgs]


def test_create_thread_default_active_leaf(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    view = store.create_thread(title="T")
    thread = view["threads"][0]
    assert thread["active_leaf_id"] == ""
    assert thread["messages"] == []


def test_append_turn_chains_parent_and_updates_leaf(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])

    store.append_turn("t", "q1", "a1")
    view = store.list_view()
    thread = view["threads"][0]
    msgs = thread["messages"]
    assert len(msgs) == 2
    assert msgs[0]["parent_id"] == ""
    assert msgs[0]["role"] == "user"
    assert msgs[1]["parent_id"] == msgs[0]["id"]
    assert msgs[1]["role"] == "assistant"
    assert thread["active_leaf_id"] == msgs[1]["id"]

    store.append_turn("t", "q2", "a2")
    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    assert len(msgs) == 4
    # q2 parents to a1 (the previous active leaf)
    assert msgs[2]["parent_id"] == msgs[1]["id"]
    assert msgs[3]["parent_id"] == msgs[2]["id"]
    assert view["threads"][0]["active_leaf_id"] == msgs[3]["id"]


def test_append_turn_fork_preserves_original_branch(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    u1_id = msgs[0]["id"]
    a1_id = msgs[1]["id"]

    # fork from the first user message (an ancestor, not the active leaf)
    store.append_turn("t", "q2", "a2", parent_message_id=u1_id)

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    assert len(msgs) == 4
    u2 = msgs[2]
    a2 = msgs[3]
    assert u2["parent_id"] == u1_id
    assert a2["parent_id"] == u2["id"]
    assert view["threads"][0]["active_leaf_id"] == a2["id"]

    # original branch still present and unchanged
    assert msgs[1]["id"] == a1_id
    assert msgs[1]["parent_id"] == u1_id

    # active path follows the new fork: u1 -> u2 -> a2 (not u1 -> a1)
    path = store.active_path("t")
    assert [m["id"] for m in path] == [u1_id, u2["id"], a2["id"]]


def test_active_path_walks_leaf_to_root_reversed(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")
    store.append_turn("t", "q2", "a2")

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    u1, a1, u2, a2 = msgs

    path = store.active_path("t")
    assert [m["id"] for m in path] == [u1["id"], a1["id"], u2["id"], a2["id"]]
    assert path[0]["parent_id"] == ""
    assert path[-1]["id"] == view["threads"][0]["active_leaf_id"]


def test_active_path_filters_archived_nodes(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    # seed a thread where a node on the active path is archived
    store.replace_all(
        current_id="t",
        threads=[
            {
                "id": "t",
                "title": "T",
                "messages": [
                    {"id": "m1", "parent_id": "", "role": "user", "text": "q1", "archived": False},
                    {"id": "m2", "parent_id": "m1", "role": "assistant", "text": "a1", "archived": True},
                    {"id": "m3", "parent_id": "m2", "role": "user", "text": "q2", "archived": False},
                    {"id": "m4", "parent_id": "m3", "role": "assistant", "text": "a2", "archived": False},
                ],
                "active_leaf_id": "m4",
            }
        ],
    )
    path = store.active_path("t")
    ids = [m["id"] for m in path]
    # m2 is archived → excluded
    assert "m2" not in ids
    assert ids == ["m1", "m3", "m4"]


def test_set_active_leaf_changes_active_path(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")
    # fork from root user message
    view = store.list_view()
    u1_id = view["threads"][0]["messages"][0]["id"]
    store.append_turn("t", "q2", "a2", parent_message_id=u1_id)

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    a1_id = msgs[1]["id"]
    a2_id = msgs[3]["id"]

    # active path currently follows the fork (ends at a2)
    assert [m["id"] for m in store.active_path("t")] == [u1_id, msgs[2]["id"], a2_id]

    # switch back to the original branch leaf
    store.set_active_leaf("t", a1_id)
    path = store.active_path("t")
    assert [m["id"] for m in path] == [u1_id, a1_id]

    # invalid leaf id → no change
    store.set_active_leaf("t", "does_not_exist")
    assert store.list_view()["threads"][0]["active_leaf_id"] == a1_id


def test_agent_history_uses_active_path_and_truncates(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    # build a single linear branch longer than MAX_HISTORY_MESSAGES
    messages = []
    for i in range(MAX_HISTORY_MESSAGES + 10):
        messages.append({"role": "user", "text": f"q{i}"})
        messages.append({"role": "assistant", "text": f"a{i}"})
    store.replace_all(
        current_id="t",
        threads=[{"id": "t", "title": "Long", "messages": messages}],
    )

    history = store.agent_history("t")
    assert len(history) == MAX_HISTORY_MESSAGES
    # 148 messages total; last 64 start at index 84 == 2*42 → q42
    total = (MAX_HISTORY_MESSAGES + 10) * 2
    first_kept_index = total - MAX_HISTORY_MESSAGES
    first_kept_i = first_kept_index // 2
    assert history[0] == {"role": "user", "content": f"q{first_kept_i}"}
    assert history[-1] == {"role": "assistant", "content": f"a{(MAX_HISTORY_MESSAGES + 10) - 1}"}


def test_rollback_to_archives_descendants_and_sets_leaf(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")
    store.append_turn("t", "q2", "a2")

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    u1_id, a1_id, u2_id, a2_id = [m["id"] for m in msgs]

    store.rollback_to("t", a1_id)

    view = store.list_view()
    thread = view["threads"][0]
    by_id = {m["id"]: m for m in thread["messages"]}
    assert by_id[a1_id]["archived"] is False  # target not archived
    assert by_id[u2_id]["archived"] is True
    assert by_id[a2_id]["archived"] is True
    assert thread["active_leaf_id"] == a1_id

    path = store.active_path("t")
    assert [m["id"] for m in path] == [u1_id, a1_id]

    # rolling back to a non-existent id is a no-op
    before = store.list_view()["threads"][0]["active_leaf_id"]
    store.rollback_to("t", "missing_id")
    assert store.list_view()["threads"][0]["active_leaf_id"] == before


def test_rollback_then_append_continues_from_rollback_point(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")
    store.append_turn("t", "q2", "a2")

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    u1_id = msgs[0]["id"]
    a1_id = msgs[1]["id"]

    store.rollback_to("t", a1_id)
    store.append_turn("t", "q3", "a3")  # parents to active leaf (a1)

    view = store.list_view()
    thread = view["threads"][0]
    msgs = thread["messages"]
    u3 = msgs[-2]
    a3 = msgs[-1]
    assert u3["parent_id"] == a1_id
    assert a3["parent_id"] == u3["id"]
    assert u3["archived"] is False
    assert a3["archived"] is False
    assert thread["active_leaf_id"] == a3["id"]

    path = store.active_path("t")
    assert [m["id"] for m in path] == [u1_id, a1_id, u3["id"], a3["id"]]


def test_restore_archived_unflags_subtree(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")
    store.append_turn("t", "q2", "a2")

    view = store.list_view()
    a1_id = view["threads"][0]["messages"][1]["id"]

    store.rollback_to("t", a1_id)
    # descendants u2/a2 now archived
    by_id = {m["id"]: m for m in store.list_view()["threads"][0]["messages"]}
    assert any(m["archived"] for m in by_id.values())

    store.restore_archived("t", a1_id)

    msgs = store.list_view()["threads"][0]["messages"]
    for m in msgs:
        assert m["archived"] is False

    # restoring a non-existent id is a no-op (no crash)
    store.restore_archived("t", "missing_id")


def test_thread_tree_view_structure_and_active_flags(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(current_id="t", threads=[])
    store.append_turn("t", "q1", "a1")
    view = store.list_view()
    u1_id = view["threads"][0]["messages"][0]["id"]
    # fork from u1 (an ancestor user message)
    store.append_turn("t", "q2", "a2", parent_message_id=u1_id)

    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    a1_id = msgs[1]["id"]
    a2_id = msgs[3]["id"]

    tree = store.thread_tree_view("t")
    # turns pair user+assistant: the root turn is represented by a1 (its reply)
    assert tree["root_id"] == a1_id
    assert tree["active_leaf_id"] == a2_id

    nodes = tree["nodes"]
    assert len(nodes) == 2  # two turns, not four messages
    for n in nodes:
        assert {
            "id",
            "parent_id",
            "user_preview",
            "assistant_preview",
            "has_assistant",
            "archived",
            "active",
        } <= set(n.keys())

    active_flags = {n["id"]: n["active"] for n in nodes}
    # active path is u1 -> u2 -> a2, so only the forked turn (a2) is active
    assert active_flags[a1_id] is False
    assert active_flags[a2_id] is True

    # turn parent_id resolves through the message→turn map: the forked turn's
    # parent is the first turn (a1), even though it forked from u1 directly
    node_by_id = {n["id"]: n for n in nodes}
    assert node_by_id[a2_id]["parent_id"] == a1_id
    assert node_by_id[a1_id]["user_preview"] == "q1"
    assert node_by_id[a1_id]["assistant_preview"] == "a1"
    assert node_by_id[a1_id]["has_assistant"] is True

    # preview is text truncated to 80 chars (user_preview when no assistant)
    long_text = "x" * 200
    store.replace_all(
        current_id="t2",
        threads=[{"id": "t2", "title": "T2", "messages": [{"role": "user", "text": long_text}]}],
    )
    tree2 = store.thread_tree_view("t2")
    assert tree2["nodes"][0]["user_preview"] == "x" * 80
    assert tree2["nodes"][0]["has_assistant"] is False


def test_replace_all_handles_mixed_old_and_new_messages(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    store.replace_all(
        current_id="t",
        threads=[
            {
                "id": "t",
                "title": "Mixed",
                "messages": [
                    {"role": "user", "text": "old1"},  # no id/parent_id/archived
                    {"id": "m2", "role": "assistant", "text": "new1"},  # id, no parent_id
                    {"role": "bot", "text": "  bot msg  "},  # bot + whitespace, no id
                ],
            }
        ],
    )
    view = store.list_view()
    thread = view["threads"][0]
    msgs = thread["messages"]
    assert len(msgs) == 3

    # first: backfilled id, parent_id == "", archived False
    assert msgs[0]["id"].startswith("m_")
    assert msgs[0]["parent_id"] == ""
    assert msgs[0]["role"] == "user"
    assert msgs[0]["archived"] is False

    # second: keeps provided id, parent_id chained to first
    assert msgs[1]["id"] == "m2"
    assert msgs[1]["parent_id"] == msgs[0]["id"]
    assert msgs[1]["role"] == "assistant"

    # third: bot → assistant, text stripped, id generated, parent chained to m2
    assert msgs[2]["id"].startswith("m_")
    assert msgs[2]["parent_id"] == "m2"
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["text"] == "bot msg"

    assert thread["active_leaf_id"] == msgs[2]["id"]


def test_replace_all_respects_max_thread_messages(tmp_path: Path) -> None:
    store = ChatThreadStore(tmp_path / "chat_threads.json")
    messages = [{"role": "user", "text": f"q{i}"} for i in range(MAX_THREAD_MESSAGES + 50)]
    store.replace_all(current_id="t", threads=[{"id": "t", "title": "Big", "messages": messages}])
    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    assert len(msgs) == MAX_THREAD_MESSAGES
    # kept the tail
    assert msgs[-1]["text"] == f"q{MAX_THREAD_MESSAGES + 50 - 1}"
    assert msgs[0]["text"] == f"q{50}"
    # active_leaf still valid (last retained id)
    assert view["threads"][0]["active_leaf_id"] == msgs[-1]["id"]
