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


def test_graph_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/graph?filter=personal")
    assert response.status_code == 200
    payload = response.json()
    assert "nodes" in payload
    assert "edges" in payload


def test_kb_tree_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/kb/tree")
    assert response.status_code == 200
    payload = response.json()
    assert "topics" in payload
    assert payload["legacy_workspace"] is True


def test_kb_note_update_endpoint() -> None:
    client = TestClient(app)
    rebuild = client.post("/api/kb/rebuild")
    assert rebuild.status_code == 200
    assert rebuild.json()["legacy_workspace"] is True

    notes_payload = client.get("/api/kb/notes").json()
    assert notes_payload["legacy_workspace"] is True
    notes = notes_payload["notes"]
    if not notes:
        return

    path = notes[0]["path"]
    updated_content = "---\ntitle: test\n---\n\n用户编辑内容"
    response = client.put("/api/kb/note", json={"path": path, "content": updated_content})
    assert response.status_code == 200
    assert response.json()["content"] == updated_content


def test_durable_memory_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/memory/durable")
    assert response.status_code == 200
    payload = response.json()
    assert "memory_md" in payload
    assert "user_md" in payload

    put_response = client.put(
        "/api/memory/durable",
        json={"memory_md": "Test env fact", "user_md": "Name: Tester"},
    )
    assert put_response.status_code == 200
    updated = put_response.json()
    assert updated["memory_md"] == "Test env fact"
    assert updated["user_md"] == "Name: Tester"


def test_platform_settings_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/settings/platforms")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 7
    assert payload[0]["name"]
