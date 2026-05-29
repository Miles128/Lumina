"""Tests for agent chat service."""

from pathlib import Path
from unittest.mock import patch

from secretary.agent.chat_service import ChatService
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import LoopResult
from secretary.agent.skills import SkillManager
from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.services.profile_service import ProfileService
from secretary.services.user_profile_store import UserProfileStore


def _build_chat_service(tmp_path: Path, *, api_key: str = "") -> ChatService:
    settings = Settings(
        data_dir=tmp_path / "data",
        llm_api_key=api_key,
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
        prompt_gate_enabled=False,
    )
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    profiler = LocalDocumentsProfiler(settings)
    profile_service = ProfileService(
        settings,
        store,
        profiler,
        UserProfileStore(settings.resolved_data_dir() / "user_profile.md"),
    )
    skills = SkillManager(settings.resolved_data_dir())
    return ChatService(settings, store, profile_service, skills)


def test_chat_fallback_without_llm(tmp_path: Path) -> None:
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=None):
        service = _build_chat_service(tmp_path)
        result = service.reply("你好，今天天气怎么样")
    assert result.used_llm is False
    assert "你好" in result.reply
    assert "还没有查到相关的本地记忆" not in result.reply


def test_build_tools_includes_p0_agent_tools(tmp_path: Path) -> None:
    service = _build_chat_service(tmp_path)
    names = {tool.name for tool in service._build_tools()}
    expected = {
        "list_dir",
        "file_read",
        "file_write",
        "file_delete",
        "shell",
        "search_memory",
        "web_search",
        "web_fetch",
        "memory",
        "session_search",
    }
    assert expected <= names


def test_chat_uses_llm_without_memory(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch(
            "secretary.agent.loop.chat_completion",
            return_value="我可以正常聊天，本地记忆为空也没关系。",
        ):
            service = _build_chat_service(tmp_path, api_key="test-key")
            result = service.reply("帮我写一句早安")
    assert result.used_llm is True
    assert "正常聊天" in result.reply


def test_chat_sync_gate_routes_without_llm(tmp_path: Path) -> None:
    from secretary.memory.db import MemoryStore
    from secretary.services.sync import SyncService

    settings = Settings(data_dir=tmp_path / "data", prompt_gate_enabled=True)
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    service = ChatService(
        settings,
        store,
        ProfileService(
            settings,
            store,
            LocalDocumentsProfiler(settings),
            UserProfileStore(settings.resolved_data_dir() / "user_profile.md"),
        ),
        SkillManager(settings.resolved_data_dir()),
        sync_service=SyncService(settings, store),
    )
    with patch.object(service._sync_service, "sync_all", return_value=[]):
        result = service.reply("帮我同步全部数据")
    assert "同步完成" in result.reply
    assert result.used_llm is False


def test_chat_profile_gate_returns_profile_markdown(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", prompt_gate_enabled=True)
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    profile_store = UserProfileStore(settings.resolved_data_dir() / "user_profile.md")
    profile_store.save("# 我是测试用户\n\n喜欢 Python。")
    service = ChatService(
        settings,
        store,
        ProfileService(
            settings,
            store,
            LocalDocumentsProfiler(settings),
            profile_store,
        ),
        SkillManager(settings.resolved_data_dir()),
    )
    result = service.reply("我的个人画像是什么样的")
    assert "测试你" in result.reply
    assert result.used_llm is False


def test_chat_uses_turn_orchestrator_for_agent_loop(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    fake_result = LoopResult(reply="好的，我来处理。", steps=[], used_tools=[], total_steps=1)
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch.object(
            service._turn_orchestrator,
            "run_agent_turn",
            return_value=fake_result,
        ) as mocked:
            result = service.reply("帮我整理一下")
    assert mocked.called
    assert result.reply == "好的，我来处理。"


def test_prepare_user_reply_runs_rewriter_then_sanitizer(tmp_path: Path) -> None:
    service = _build_chat_service(tmp_path, api_key="test-key")
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    with patch(
        "secretary.agent.chat_service.rewrite_if_forbidden_label",
        return_value="用户未明确需求，等待用户补充",
    ) as mocked:
        reply = service._prepare_user_reply("原句", "继续", config)
    assert mocked.called
    assert "用户" not in reply


def test_chat_forces_shell_confirmation_from_bash_block(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    prompt = "先搜\n```bash\npwd\n```\n等 shell 结果。"
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch.object(service._turn_orchestrator, "run_agent_turn") as mocked:
            result = service.reply(prompt)
    assert not mocked.called
    assert result.pending_confirmation is not None
    assert result.pending_confirmation.tool_name == "shell"
    assert result.pending_confirmation.arguments["command"] == "pwd"
