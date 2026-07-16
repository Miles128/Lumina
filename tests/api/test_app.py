"""API tests."""

from fastapi.testclient import TestClient

from secretary.api.app import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 7


def test_profile_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/profile")
    assert response.status_code == 200
    payload = response.json()
    assert "markdown" in payload
    assert "sections" in payload


def test_chat_endpoint() -> None:
    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "我最近在读什么"})
    assert response.status_code == 200
    payload = response.json()
    assert "reply" in payload
    assert "usage_total_tokens" in payload


def test_chat_thread_endpoints() -> None:
    client = TestClient(app)
    created = client.post("/api/chat/threads", json={"title": "API thread"})
    assert created.status_code == 200
    payload = created.json()
    thread_id = payload["current_id"]
    assert thread_id
    assert any(item["id"] == thread_id for item in payload["threads"])

    switched = client.put("/api/chat/threads/current", json={"thread_id": thread_id})
    assert switched.status_code == 200
    assert switched.json()["current_id"] == thread_id

    deleted = client.delete(f"/api/chat/threads/{thread_id}")
    assert deleted.status_code == 200
    assert all(item["id"] != thread_id for item in deleted.json()["threads"])


def test_durable_memory_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/memory/durable")
    assert response.status_code == 200
    payload = response.json()
    assert "memory_md" in payload
    # USER.md 已退役，不再返回
    assert "user_md" not in payload

    put_response = client.put(
        "/api/memory/durable",
        json={"memory_md": "Test env fact"},
    )
    assert put_response.status_code == 200
    updated = put_response.json()
    assert updated["memory_md"] == "Test env fact"
    assert "user_md" not in updated


def test_platform_settings_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/settings/platforms")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 7
    assert payload[0]["name"]


def _seed_branching_thread(client: TestClient) -> tuple[str, str, str, str, str]:
    """Create a thread with a fork (u1->a1, u1->u2->a2). Returns (thread_id, u1_id, a1_id, u2_id, a2_id)."""
    chat_service = app.state.chat_service
    created = chat_service._thread_store.create_thread(title="Branch API test")
    thread_id = created["current_id"]
    chat_service._thread_store.append_turn(thread_id, "q1", "a1")
    view = chat_service._thread_store.list_view()
    u1_id = view["threads"][0]["messages"][0]["id"]
    chat_service._thread_store.append_turn(thread_id, "q2", "a2", parent_message_id=u1_id)
    view = chat_service._thread_store.list_view()
    msgs = view["threads"][0]["messages"]
    return thread_id, u1_id, msgs[1]["id"], msgs[2]["id"], msgs[3]["id"]


def _seed_linear_thread(client: TestClient) -> tuple[str, str, str, str, str]:
    """Create a thread with a linear chain (u1->a1->u2->a2). Returns (thread_id, u1_id, a1_id, u2_id, a2_id)."""
    chat_service = app.state.chat_service
    created = chat_service._thread_store.create_thread(title="Linear API test")
    thread_id = created["current_id"]
    chat_service._thread_store.append_turn(thread_id, "q1", "a1")
    chat_service._thread_store.append_turn(thread_id, "q2", "a2")
    view = chat_service._thread_store.list_view()
    msgs = view["threads"][0]["messages"]
    return thread_id, msgs[0]["id"], msgs[1]["id"], msgs[2]["id"], msgs[3]["id"]


def test_chat_thread_tree_endpoint() -> None:
    client = TestClient(app)
    thread_id, _u1_id, a1_id, _u2_id, a2_id = _seed_branching_thread(client)
    try:
        response = client.get(f"/api/chat/threads/{thread_id}/tree")
        assert response.status_code == 200
        payload = response.json()
        # turns pair user+assistant: root is the first turn (represented by a1)
        assert payload["root_id"] == a1_id
        assert payload["active_leaf_id"] == a2_id
        assert len(payload["nodes"]) == 2
        for node in payload["nodes"]:
            assert {
                "id",
                "parent_id",
                "user_preview",
                "assistant_preview",
                "has_assistant",
                "archived",
                "active",
            } <= set(node.keys())
        active_map = {n["id"]: n["active"] for n in payload["nodes"]}
        # forked branch (u1->u2->a2) is active; original a1 branch is not
        assert active_map[a1_id] is False
        assert active_map[a2_id] is True
        # the second turn's parent resolves to the first turn's id
        node_by_id = {n["id"]: n for n in payload["nodes"]}
        assert node_by_id[a2_id]["parent_id"] == a1_id
        assert node_by_id[a1_id]["user_preview"] == "q1"
        assert node_by_id[a1_id]["assistant_preview"] == "a1"
    finally:
        client.delete(f"/api/chat/threads/{thread_id}")


def test_chat_thread_active_leaf_endpoint() -> None:
    client = TestClient(app)
    thread_id, _u1_id, a1_id, _u2_id, _a2_id = _seed_branching_thread(client)
    try:
        response = client.put(
            f"/api/chat/threads/{thread_id}/active-leaf",
            json={"leaf_id": a1_id},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["threads"][0]["active_leaf_id"] == a1_id

        # invalid leaf id → no change (still a1)
        invalid = client.put(
            f"/api/chat/threads/{thread_id}/active-leaf",
            json={"leaf_id": "does_not_exist"},
        )
        assert invalid.status_code == 200
        assert invalid.json()["threads"][0]["active_leaf_id"] == a1_id
    finally:
        client.delete(f"/api/chat/threads/{thread_id}")


def test_chat_thread_rollback_endpoint() -> None:
    client = TestClient(app)
    # linear chain so a1 has descendants (u2, a2) to archive
    thread_id, _u1_id, a1_id, u2_id, a2_id = _seed_linear_thread(client)
    try:
        response = client.post(
            f"/api/chat/threads/{thread_id}/rollback",
            json={"to_message_id": a1_id},
        )
        assert response.status_code == 200
        payload = response.json()
        thread = payload["threads"][0]
        by_id = {m["id"]: m for m in thread["messages"]}
        assert by_id[a1_id]["archived"] is False
        assert by_id[u2_id]["archived"] is True
        assert by_id[a2_id]["archived"] is True
        assert thread["active_leaf_id"] == a1_id
    finally:
        client.delete(f"/api/chat/threads/{thread_id}")


def test_chat_thread_restore_endpoint() -> None:
    client = TestClient(app)
    # linear chain so a1 has descendants to archive then restore
    thread_id, _u1_id, a1_id, u2_id, a2_id = _seed_linear_thread(client)
    chat_service = app.state.chat_service
    # archive descendants of a1 first
    chat_service._thread_store.rollback_to(thread_id, a1_id)
    try:
        response = client.post(
            f"/api/chat/threads/{thread_id}/restore",
            json={"message_id": a1_id},
        )
        assert response.status_code == 200
        payload = response.json()
        by_id = {m["id"]: m for m in payload["threads"][0]["messages"]}
        assert by_id[a1_id]["archived"] is False
        assert by_id[u2_id]["archived"] is False
        assert by_id[a2_id]["archived"] is False
    finally:
        client.delete(f"/api/chat/threads/{thread_id}")


def test_chat_request_accepts_parent_message_id() -> None:
    """ChatRequest.parent_message_id is accepted (empty default) and reaches reply."""
    client = TestClient(app)
    chat_service = app.state.chat_service
    created = chat_service._thread_store.create_thread(title="Parent id API test")
    thread_id = created["current_id"]
    # seed first turn directly via store so reply can fork from u1
    chat_service._thread_store.append_turn(thread_id, "q1", "a1")
    u1_id = chat_service._thread_store.list_view()["threads"][0]["messages"][0]["id"]
    try:
        from unittest.mock import patch

        from secretary.agent.llm_config import LlmConfig

        config = LlmConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
            source="env",
        )
        with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
            with patch(
                "secretary.agent.chat_service.chat_completion",
                return_value="好的。",
            ):
                response = client.post(
                    "/api/chat",
                    json={
                        "message": "换个方向",
                        "thread_id": thread_id,
                        "parent_message_id": u1_id,
                    },
                )
        assert response.status_code == 200
        view = chat_service._thread_store.list_view()
        msgs = view["threads"][0]["messages"]
        # new user message forked from u1, not from a1
        u2 = msgs[2]
        assert u2["parent_id"] == u1_id
    finally:
        client.delete(f"/api/chat/threads/{thread_id}")
