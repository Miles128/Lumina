"""PRD v0.1.1 API-level E2E smoke tests (no Electron, mock LLM where needed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import LoopResult
from secretary.agent.chat_service import ChatResult
from secretary.api.app import app
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind

pytestmark = pytest.mark.e2e


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="smoke-test-key",
        base_url="https://example.com/v1",
        model="smoke-model",
        source="env",
    )


def test_smoke_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) >= 7


def test_smoke_shibei_config(client: TestClient) -> None:
    response = client.get("/api/shibei/config")
    assert response.status_code == 200
    payload = response.json()
    assert "sources" in payload
    assert "enabled" in payload
    assert isinstance(payload["sources"], list)


def test_smoke_identity_without_llm(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "你是谁"})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("reply")
    assert payload.get("usage_total_tokens", 0) == 0


def test_smoke_author_without_llm(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "谁是你的作者"})
    assert response.status_code == 200
    payload = response.json()
    assert "四海" in payload.get("reply", "") or "灵犀" in payload.get("reply", "")


def test_smoke_greeting_with_mock_llm(client: TestClient, mock_llm_config: LlmConfig) -> None:
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=mock_llm_config):
        with patch(
            "secretary.agent.chat_service.chat_completion",
            return_value="你好，我是灵犀。",
        ):
            response = client.post("/api/chat", json={"message": "你好"})
    assert response.status_code == 200
    payload = response.json()
    assert "你好" in payload.get("reply", "")
    assert payload.get("usage_total_tokens", 0) >= 0


def test_smoke_weread_empty_prompts_sync(client: TestClient, mock_llm_config: LlmConfig) -> None:
    sync = client.app.state.sync_service
    health = [
        ConnectorHealth(
            source=SourceKind.WEREAD,
            status=ConnectorStatus.READY,
            message="ok",
            item_count=0,
        )
    ]
    with patch.object(sync, "get_stored_health", return_value=health):
        with patch("secretary.agent.chat_service.resolve_llm_config", return_value=mock_llm_config):
            response = client.post(
                "/api/chat",
                json={"message": "我微信读书最近在读什么"},
            )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("route") == "sync_empty"
    assert "同步" in payload.get("reply", "")


def test_smoke_filesystem_agent_uses_list_dir(
    client: TestClient,
    mock_llm_config: LlmConfig,
) -> None:
    loop_result = LoopResult(
        reply="📁 Lumina\n📁 NoteAI",
        steps=[],
        used_tools=["list_dir"],
        total_steps=2,
        grounding_verified=True,
    )
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=mock_llm_config):
        with patch(
            "secretary.agent.chat_service.ChatService._run_agent",
            return_value=ChatResult(
                reply=loop_result.reply,
                profile_excerpt="",
                used_llm=True,
                memory_hits=0,
                used_tools=loop_result.used_tools,
                total_steps=loop_result.total_steps,
                grounding_verified=True,
            ),
        ):
            response = client.post(
                "/api/chat",
                json={"message": "My Projects 里有哪些文件夹"},
            )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("grounding_verified") is True
    assert "list_dir" in (payload.get("used_tools") or [])


def test_smoke_chat_confirm_cancel(client: TestClient) -> None:
    response = client.post(
        "/api/chat/confirm",
        json={"approved": False, "action_id": "smoke-no-op", "trace_id": ""},
    )
    assert response.status_code == 200
    assert "取消" in response.json().get("reply", "")


def test_smoke_third_party_project_author(client: TestClient, tmp_path: Path) -> None:
    from secretary.config import settings

    projects = tmp_path / "My Projects"
    repo = projects / "open-design"
    repo.mkdir(parents=True)
    (repo / "package.json").write_text(
        '{"name":"open-design","license":"Apache-2.0"}',
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Open Design\n", encoding="utf-8")

    with patch.object(settings, "projects_dir", str(projects)):
        response = client.post("/api/chat", json={"message": "找 open design 的作者"})
    assert response.status_code == 200
    payload = response.json()
    assert "open-design" in payload.get("reply", "")
    assert "四海" not in payload.get("reply", "")
