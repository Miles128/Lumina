"""HTTP tests for IDP observation API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from secretary.agent.idp import PROTOCOL_ID, build_envelope, get_idp_store
from secretary.api.app import app


def test_get_chat_idp_empty_trace() -> None:
    client = TestClient(app)
    resp = client.get("/api/chat/idp/no-such-trace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["protocol"] == PROTOCOL_ID
    assert body["peer_channel_allowed"] is False
    assert body["delegations"] == []
    assert "topology" in body
    assert body["role_display_names"]["worker"] == "执行者"


def test_get_chat_idp_returns_delegations() -> None:
    store = get_idp_store()
    tid = "api-idp-trace"
    store.clear(tid)
    env = build_envelope(
        run_id="run-api",
        goal="probe",
        archetype="explore",
        tool_names={"read"},
        max_rounds=3,
    )
    store.begin(tid, env)
    store.transition(tid, "run-api", "running")
    try:
        client = TestClient(app)
        resp = client.get(f"/api/chat/idp/{tid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trace_id"] == tid
        assert len(body["delegations"]) == 1
        assert body["delegations"][0]["envelope"]["run_id"] == "run-api"
        assert body["delegations"][0]["state"] == "running"
    finally:
        store.clear(tid)
