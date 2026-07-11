"""Tests for multi-kind pause persistence and restart restore."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.chat_service import ChatService
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import PendingConfirmation, StepResult
from secretary.agent.session_store import (
    SessionStore,
    pause_bundle_confirmation,
    pause_bundle_parent,
    pause_bundle_subagent,
)
from secretary.agent.skills import SkillManager
from secretary.agent.subagent.resume import ParentTurnResumeState, SubAgentResumeState
from secretary.agent.tools.base import ToolCall
from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.services.profile_service import ProfileService
from secretary.services.user_profile_store import UserProfileStore


def _llm() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def _pending(**kwargs: object) -> PendingConfirmation:
    base = {
        "action_id": "act_1",
        "tool_name": "file_write",
        "arguments": {"path": "x.txt", "content": "hi"},
        "description": "write file",
        "risk_level": "medium",
        "confirmation_kind": "action",
    }
    base.update(kwargs)
    return PendingConfirmation(**base)  # type: ignore[arg-type]


def test_session_store_merges_multi_kind_pauses(tmp_path: Path) -> None:
    path = tmp_path / "turns.json"
    store = SessionStore(persistence_path=path)
    store.save_pause(
        "trace-m",
        kind="subagent",
        data={"run_id": "run_1", "pending": {"action_id": "a", "tool_name": "shell"}},
    )
    store.save_pause(
        "trace-m",
        kind="parent_resume",
        data={"session_id": "sess", "tool_names": ["shell"]},
    )
    store.save_pause(
        "trace-m",
        kind="confirmation",
        data={
            "pending": {
                "action_id": "act_1",
                "tool_name": "shell",
                "arguments": {"command": "echo hi"},
                "description": "run",
                "risk_level": "high",
                "confirmation_kind": "shell",
            },
            "messages": [{"role": "user", "content": "run"}],
        },
    )

    reloaded = SessionStore(persistence_path=path)
    entry = reloaded.load_pauses("trace-m")
    assert set(entry) == {"confirmation", "subagent", "parent_resume"}
    assert entry["subagent"]["run_id"] == "run_1"
    assert entry["parent_resume"]["session_id"] == "sess"
    assert entry["confirmation"]["pending"]["tool_name"] == "shell"


def test_session_store_upgrades_legacy_single_kind(tmp_path: Path) -> None:
    path = tmp_path / "turns.json"
    path.write_text(
        """{
  "turns": {},
  "pauses": {
    "legacy": {
      "kind": "confirmation",
      "data": {
        "pending": {
          "action_id": "a",
          "tool_name": "shell",
          "arguments": {},
          "description": "x",
          "risk_level": "high",
          "confirmation_kind": "shell"
        },
        "messages": []
      }
    }
  }
}
""",
        encoding="utf-8",
    )
    store = SessionStore(persistence_path=path)
    entry = store.load_pauses("legacy")
    assert set(entry) == {"confirmation"}
    assert entry["confirmation"]["pending"]["tool_name"] == "shell"


def _build_service(tmp_path: Path, *, store: SessionStore) -> ChatService:
    settings = Settings(
        data_dir=tmp_path / "data",
        llm_api_key="test-key",
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
        prompt_gate_enabled=False,
    )
    memory = MemoryStore(settings.resolved_data_dir() / "memory.db")
    profile_service = ProfileService(
        settings,
        memory,
        LocalDocumentsProfiler(settings),
        UserProfileStore(settings.resolved_data_dir() / "user_profile.md"),
    )
    return ChatService(
        settings,
        memory,
        profile_service,
        SkillManager(settings.resolved_data_dir()),
        session_store=store,
    )


def test_restart_restores_subagent_stack_and_spawn_tool(tmp_path: Path) -> None:
    path = tmp_path / "turns.json"
    store = SessionStore(persistence_path=path)
    llm = _llm()
    pending = _pending()
    sub = SubAgentResumeState(
        run_id="run_sub",
        archetype="worker",
        goal="write marker",
        context="",
        child_session_id="child-1",
        parent_session_id="parent-sess",
        messages=[{"role": "user", "content": "write"}],
        max_steps=8,
        working_dir=tmp_path,
        pending=pending,
        llm_config=llm,
        temperature=0.5,
        pending_step=StepResult(
            thought="",
            tool_call=ToolCall(name="file_write", arguments={"path": "x.txt", "content": "hi"}),
            tool_output=None,
            needs_confirmation=True,
        ),
        steps_completed=1,
        used_tools=["file_write"],
    )
    parent = ParentTurnResumeState(
        messages_snapshot=[{"role": "user", "content": "delegate"}],
        tools=[],
        max_steps=8,
        pending_step=StepResult(
            thought="",
            tool_call=ToolCall(
                name="spawn_subagent",
                arguments={"goal": "write marker", "archetype": "worker"},
            ),
            tool_output=None,
            needs_confirmation=False,
        ),
        assistant_message=None,
        native_used=True,
        step_idx=0,
        llm_config=llm,
        session_id="parent-sess",
        user_message="delegate",
        profile_excerpt="",
        memory_hits=0,
    )

    store.save_pause("trace-restart", kind="subagent", data=pause_bundle_subagent(sub))
    store.save_pause("trace-restart", kind="parent_resume", data=pause_bundle_parent(parent))
    store.save_pause(
        "trace-restart",
        kind="confirmation",
        data=pause_bundle_confirmation(
            pending=pending,
            messages=[{"role": "user", "content": "delegate"}],
        ),
    )

    # Simulate process restart: fresh ChatService, empty in-memory pause state.
    service = _build_service(tmp_path, store=SessionStore(persistence_path=path))
    assert service._active_spawn_tool is None
    assert service._subagent_pending is None

    with patch("secretary.agent.chat_service.resolve_llm_config", return_value=llm):
        service._restore_pause_from_store("trace-restart")

    assert service._active_spawn_tool is not None
    assert service._subagent_pending is not None
    assert service._subagent_pending.run_id == "run_sub"
    assert service._subagent_pending.parent_session_id == "parent-sess"
    assert service._parent_turn_resume is not None
    assert service._parent_turn_resume.session_id == "parent-sess"
    assert service._pending is not None
    assert service._pending.tool_name == "file_write"
    assert service._active_spawn_tool._spawn_context.parent_session_id == "parent-sess"
