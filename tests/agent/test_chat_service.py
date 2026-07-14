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
    names = {tool.name for tool in service._tool_registry.build_tools()}
    expected = {
        "list_dir",
        "file_read",
        "read_document",
        "file_write",
        "file_delete",
        "shell",
        "code_exec",
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


def test_chat_sync_empty_weread_without_data(tmp_path: Path) -> None:
    from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
    from secretary.services.sync import SyncService

    settings = Settings(
        data_dir=tmp_path / "data",
        prompt_gate_enabled=False,
        llm_api_key="test-key",
    )
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)
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
        sync_service=sync,
    )
    with patch.object(
        sync,
        "get_stored_health",
        return_value=[
            ConnectorHealth(
                source=SourceKind.WEREAD,
                status=ConnectorStatus.READY,
                message="ok",
                item_count=0,
            )
        ],
    ):
        with patch("secretary.agent.chat_service.resolve_llm_config") as resolve:
            resolve.return_value = LlmConfig(
                api_key="k",
                base_url="https://example.com/v1",
                model="m",
                source="env",
            )
            result = service.reply("我微信读书最近在读什么")
    assert result.used_llm is False
    assert result.route == "sync_empty"
    assert "同步" in result.reply


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


def _web_agent_loop_result(reply: str) -> LoopResult:
    return LoopResult(
        reply=reply,
        steps=[],
        used_tools=["web_search"],
        total_steps=2,
        grounding_verified=True,
    )


def test_chat_weather_without_location_still_web_searches(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch.object(
            service._turn_orchestrator,
            "run_agent_turn",
            return_value=_web_agent_loop_result("今天多云。"),
        ):
            result = service.reply("今天天气怎么样")
    assert result.route == "web_agent"
    assert "web_search" in (result.used_tools or [])


def test_chat_weather_with_city_uses_web_search(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch.object(
            service._turn_orchestrator,
            "run_agent_turn",
            return_value=_web_agent_loop_result("杭州今天晴，约 18°C。"),
        ):
            result = service.reply("杭州天气怎么样")
    assert "web_search" in (result.used_tools or [])
    assert "18" in result.reply
    assert result.route == "web_agent"


def test_chat_web_search_markers_use_unified_pipeline(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch.object(
            service._turn_orchestrator,
            "run_agent_turn",
            return_value=_web_agent_loop_result("OpenAI 最近发布了新模型。"),
        ):
            result = service.reply("搜一下 OpenAI 最新动态")
    assert "web_search" in (result.used_tools or [])
    assert result.route == "web_agent"


def test_chat_weather_with_location_city_uses_web_search(tmp_path: Path) -> None:
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service = _build_chat_service(tmp_path, api_key="test-key")
    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=config):
        with patch.object(
            service._turn_orchestrator,
            "run_agent_turn",
            return_value=_web_agent_loop_result("杭州今天晴，约 20°C。"),
        ):
            result = service.reply(
                "今天天气怎么样",
                location_city="杭州",
                location_lat=30.27,
                location_lng=120.15,
            )
    assert "web_search" in (result.used_tools or [])
    assert "20" in result.reply
    assert result.route == "web_agent"


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
    assert "list_dir" in result.reply or "file_read" in result.reply
    assert result.grounding_verified is False


def test_prepare_user_reply_runs_rewriter_then_sanitizer(tmp_path: Path) -> None:
    service = _build_chat_service(tmp_path, api_key="test-key")
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    with patch(
        "secretary.agent.reply_rewriter.rewrite_if_forbidden_label",
        return_value="用户未明确需求，等待用户补充",
    ) as mocked:
        reply = service._prepare_user_reply("原句", "继续", config)
    assert mocked.called
    assert "用户" not in reply[0]


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


def test_chat_reply_with_parent_message_id_forks_thread(tmp_path: Path) -> None:
    """Task 3: reply(parent_message_id=...) should fork from the given ancestor."""
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
            service = _build_chat_service(tmp_path, api_key="test-key")
            view = service._thread_store.create_thread(title="T")
            thread_id = view["current_id"]

            # first turn: u1 -> a1 (active leaf becomes a1)
            service.reply("你好", thread_id=thread_id)
            view = service._thread_store.list_view()
            msgs = view["threads"][0]["messages"]
            assert len(msgs) == 2
            u1_id = msgs[0]["id"]
            a1_id = msgs[1]["id"]
            assert msgs[0]["parent_id"] == ""
            assert msgs[1]["parent_id"] == u1_id
            assert view["threads"][0]["active_leaf_id"] == a1_id

            # fork from u1 (an ancestor, not the active leaf a1)
            service.reply(
                "换个方向",
                thread_id=thread_id,
                parent_message_id=u1_id,
            )
            view = service._thread_store.list_view()
            msgs = view["threads"][0]["messages"]
            assert len(msgs) == 4
            u2 = msgs[2]
            a2 = msgs[3]
            # the new user message parents to the fork point u1, not a1
            assert u2["parent_id"] == u1_id
            assert a2["parent_id"] == u2["id"]
            # active leaf updated to the new assistant message
            assert view["threads"][0]["active_leaf_id"] == a2["id"]

            # active path follows the fork: u1 -> u2 -> a2 (not u1 -> a1)
            path = service._thread_store.active_path(thread_id)
            assert [m["id"] for m in path] == [u1_id, u2["id"], a2["id"]]


def test_chat_reply_default_parent_chains_to_active_leaf(tmp_path: Path) -> None:
    """Without parent_message_id, new turn chains to the current active leaf."""
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
            service = _build_chat_service(tmp_path, api_key="test-key")
            view = service._thread_store.create_thread(title="T")
            thread_id = view["current_id"]

            service.reply("你好", thread_id=thread_id)
            view = service._thread_store.list_view()
            a1_id = view["threads"][0]["messages"][1]["id"]

            # second turn without parent_message_id → chains to a1 (active leaf)
            service.reply("继续", thread_id=thread_id)
            view = service._thread_store.list_view()
            msgs = view["threads"][0]["messages"]
            u2 = msgs[2]
            assert u2["parent_id"] == a1_id


def test_chat_service_thread_wrappers(tmp_path: Path) -> None:
    """Task 4 wrappers: set_thread_active_leaf / thread_tree / rollback_thread / restore_thread."""
    service = _build_chat_service(tmp_path)
    store = service._thread_store

    # --- forked thread for tree + active-leaf ---
    view = store.create_thread(title="T")
    thread_id = view["current_id"]
    store.append_turn(thread_id, "q1", "a1")
    view = store.list_view()
    u1_id = view["threads"][0]["messages"][0]["id"]
    # fork from u1
    store.append_turn(thread_id, "q2", "a2", parent_message_id=u1_id)
    view = store.list_view()
    msgs = view["threads"][0]["messages"]
    a1_id = msgs[1]["id"]
    a2_id = msgs[3]["id"]

    # thread_tree (turns pair user+assistant: root is the first turn, repr by a1)
    tree = service.thread_tree(thread_id)
    assert tree["root_id"] == a1_id
    assert tree["active_leaf_id"] == a2_id
    assert len(tree["nodes"]) == 2

    # set_thread_active_leaf → switch to original branch
    switched = service.set_thread_active_leaf(thread_id, a1_id)
    assert switched["threads"][0]["active_leaf_id"] == a1_id

    # --- linear thread for rollback/restore (needs real descendants) ---
    linear_view = store.create_thread(title="Linear")
    linear_id = linear_view["current_id"]
    store.append_turn(linear_id, "q1", "a1")
    store.append_turn(linear_id, "q2", "a2")  # u2 parents to a1 (active leaf)
    lview = store.list_view()
    linear_thread = next(t for t in lview["threads"] if t["id"] == linear_id)
    lmsgs = linear_thread["messages"]
    _lu1_id, la1_id, lu2_id, la2_id = [m["id"] for m in lmsgs]

    # rollback_thread to a1 archives its descendants (u2, a2)
    rolled = service.rollback_thread(linear_id, la1_id)
    by_id = {m["id"]: m for m in rolled["threads"][0]["messages"]}
    assert by_id[la1_id]["archived"] is False
    assert by_id[lu2_id]["archived"] is True
    assert by_id[la2_id]["archived"] is True
    assert rolled["threads"][0]["active_leaf_id"] == la1_id

    # restore_thread un-archives the subtree
    restored = service.restore_thread(linear_id, la1_id)
    for m in restored["threads"][0]["messages"]:
        assert m["archived"] is False


def test_confirm_deny_does_not_create_system_user_turn(tmp_path: Path) -> None:
    from secretary.agent.loop import PendingConfirmation

    service = _build_chat_service(tmp_path)
    created = service.create_thread(title="新对话")
    thread_id = str(created["current_id"])
    service._thread_store.append_turn(thread_id, "请执行命令", "需要确认后才能执行。")
    pending = PendingConfirmation(
        action_id="act_test",
        tool_name="shell",
        arguments={"command": "echo hi"},
        description="执行命令",
        risk_level="medium",
        confirmation_kind="shell",
    )
    config = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    service._set_pending(pending, [{"role": "user", "content": "请执行命令"}], config, persist=False)

    result = service.confirm_action(False, thread_id=thread_id)
    assert "取消" in result.reply

    thread = next(t for t in service.list_threads()["threads"] if t["id"] == thread_id)
    roles_texts = [(m["role"], m["text"]) for m in thread["messages"]]
    assert ("user", "system") not in roles_texts
    assert any(role == "assistant" and "取消" in text for role, text in roles_texts)
    assert thread["title"] != "system"


def test_confirm_without_pending_does_not_pollute_empty_thread(tmp_path: Path) -> None:
    service = _build_chat_service(tmp_path)
    created = service.create_thread(title="新对话")
    thread_id = str(created["current_id"])

    result = service.confirm_action(False, thread_id=thread_id)
    assert "取消" in result.reply

    thread = next(t for t in service.list_threads()["threads"] if t["id"] == thread_id)
    assert thread["messages"] == []
    assert thread["title"] == "新对话"
