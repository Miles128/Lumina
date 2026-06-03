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
        result = service.reply("你好")
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
            "secretary.agent.chat_service.chat_completion",
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


def test_chat_weather_without_city_asks_location(tmp_path: Path) -> None:
    from secretary.agent.web_routing import WEATHER_ASK_LOCATION

    service = _build_chat_service(tmp_path, api_key="test-key")
    result = service.reply("今天天气怎么样")
    assert result.reply == WEATHER_ASK_LOCATION
    assert result.used_llm is False


def test_chat_weather_with_city_uses_web_search(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch(
            "secretary.agent.web_search.WebSearchTool.execute",
            return_value="🔍 '杭州 今天天气 气温' — 2 results\n1. 杭州天气\n   晴 18°C",
        ):
            with patch(
                "secretary.agent.chat_service.chat_completion",
                return_value="杭州今天晴，约 18°C。",
            ) as llm:
                result = service.reply("杭州天气怎么样")
    llm.assert_called_once()
    assert "web_search" in (result.used_tools or [])
    assert "18" in result.reply
    assert result.route == "web_search"


def test_chat_web_search_markers_use_unified_pipeline(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch(
            "secretary.agent.web_search.WebSearchTool.execute",
            return_value="🔍 '搜一下 OpenAI 最新动态' — 1 results\n1. OpenAI Blog",
        ):
            with patch(
                "secretary.agent.chat_service.chat_completion",
                return_value="OpenAI 最近发布了新模型。",
            ) as llm:
                result = service.reply("搜一下 OpenAI 最新动态")
    llm.assert_called_once()
    assert "web_search" in (result.used_tools or [])
    assert result.route == "web_search"


def test_chat_weather_with_location_city_uses_web_search(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch(
            "secretary.agent.web_search.WebSearchTool.execute",
            return_value="🔍 '杭州 今天天气 气温' — 2 results\n1. 杭州天气\n   晴 20°C",
        ):
            with patch(
                "secretary.agent.chat_service.chat_completion",
                return_value="杭州今天晴，约 20°C。",
            ) as llm:
                result = service.reply("今天天气怎么样", location_city="杭州")
    llm.assert_called_once()
    assert "web_search" in (result.used_tools or [])
    assert "20" in result.reply
    assert result.route == "web_search"


def test_chat_author_gate_is_hardcoded_without_llm(tmp_path: Path) -> None:
    from secretary.agent.identity import LUMINA_AUTHOR_REPLY

    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config") as mocked:
        with patch("secretary.agent.loop.chat_completion") as llm:
            result = service.reply("你的作者是谁")
    mocked.assert_not_called()
    llm.assert_not_called()
    assert result.reply == LUMINA_AUTHOR_REPLY
    assert result.used_llm is False
    assert result.route == "author"


def test_chat_identity_gate_is_hardcoded_without_llm(tmp_path: Path) -> None:
    from secretary.agent.identity import LUMINA_IDENTITY_INTRO

    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config") as mocked:
        with patch("secretary.agent.loop.chat_completion") as llm:
            result = service.reply("做一下自我介绍")
    mocked.assert_not_called()
    llm.assert_not_called()
    assert result.reply == LUMINA_IDENTITY_INTRO
    assert result.used_llm is False
    assert result.total_steps == 0
    assert result.route == "identity"


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
            result = service.reply("列出 src 目录下的文件")
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
