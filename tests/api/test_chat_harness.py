"""HTTP tests for chat cancel / confirm harness endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from secretary.agent.chat_service import ChatResult
from secretary.api.app import app


def test_chat_cancel_unknown_trace() -> None:
    client = TestClient(app)
    response = client.post("/api/chat/cancel", json={"trace_id": "trace_missing_xyz"})
    assert response.status_code == 200
    assert response.json() == {"cancelled": False}


def test_chat_confirm_approve_with_mocked_service() -> None:
    client = TestClient(app)
    chat_service = app.state.chat_service
    original = chat_service.confirm_action

    mock_result = ChatResult(
        reply="已执行",
        profile_excerpt="",
        used_llm=True,
        memory_hits=0,
        used_tools=["shell"],
        total_steps=2,
        route="full_agent",
        pending_confirmation=None,
        confirmation_kind="shell",
    )
    chat_service.confirm_action = MagicMock(return_value=mock_result)  # type: ignore[method-assign]
    try:
        response = client.post(
            "/api/chat/confirm",
            json={
                "action_id": "act_test",
                "approved": True,
                "trace_id": "trace_confirm_approve",
                "thread_id": "",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "已执行"
        assert payload["needs_confirmation"] is False
        assert payload["used_tools"] == ["shell"]
        chat_service.confirm_action.assert_called_once()
        kwargs = chat_service.confirm_action.call_args
        # first positional is approved=True
        assert kwargs.args[0] is True or kwargs.kwargs.get("approved") is True
    finally:
        chat_service.confirm_action = original  # type: ignore[method-assign]
