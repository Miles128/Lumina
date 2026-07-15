"""Lumina chat orchestration with Agent Loop."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from secretary.agent.agent_profile import (
    AgentProfile,
    default_max_steps_for_profile,
    effective_profile,
    parse_agent_profile,
    profile_system_appendix,
)
from secretary.agent.chat_tool_registry import ChatToolRegistry
from secretary.agent.executable_skill import ExecutableSkillManager
from secretary.agent.identity import (
    LUMINA_DEFAULT_STYLE,
    LUMINA_IDENTITY_SYSTEM_BLOCK,
    get_author_reply,
    get_identity_reply,
    is_author_request,
    is_identity_request,
)
from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig, resolve_llm_config
from secretary.agent.loop import LoopResult, PendingConfirmation
from secretary.agent.p0_tools import is_user_input_request
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.prompt_gate import GateAction, GateDecision, PromptGate
from secretary.agent.reflection import ReflectionRunner, ReflectionTrigger
from secretary.agent.reply_rewriter import (
    prepare_user_facing_reply,
)
from secretary.agent.reply_safety import is_third_person_meta_reply
from secretary.agent.session_store import (
    PauseKind,
    SessionStore,
    pause_bundle_confirmation,
    pause_bundle_parent,
    pause_bundle_subagent,
    pause_restore_confirmation,
    pause_restore_parent,
    pause_restore_subagent,
)
from secretary.agent.skills import SkillManager
from secretary.agent.soul import load_soul
from secretary.agent.subagent import SpawnSubagentTool
from secretary.agent.subagent.resume import ParentTurnResumeState, SubAgentResumeState
from secretary.agent.tools.base import Tool
from secretary.agent.turn_models import TurnContext
from secretary.agent.turn_runner import AgentTurnPlan, LoopHookBundle, TurnRunner
from secretary.agent.web_routing import (
    WebSearchPlan,
    resolve_web_search_with_llm_fallback,
)
from secretary.config import Settings
from secretary.core.types import MemoryChunk
from secretary.exceptions import AgentError
from secretary.memory.db import MemoryStore
from secretary.memory.lumina_memory import LuminaMemory
from secretary.services.agent_config import AgentConfigStore
from secretary.services.background_review import BackgroundReviewService
from secretary.services.chat_threads import ChatThreadStore
from secretary.services.file_auth import FileAuthService
from secretary.services.profile_service import ProfileService

if TYPE_CHECKING:
    from secretary.agent.mcp_manager import McpManager
    from secretary.services.shibei_service import ShibeiService
    from secretary.services.sync import SyncService

MAX_HISTORY_TURNS = 16
MAX_MESSAGE_CHARS = 2000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    reply: str
    profile_excerpt: str
    used_llm: bool
    memory_hits: int
    used_tools: list[str] | None = None
    total_steps: int = 1
    route: str = ""
    pending_confirmation: PendingConfirmation | None = None
    confirmation_kind: str = ""
    allow_permanent_read: bool = False
    allow_session_write: bool = False
    grounding_verified: bool = True
    grounding_note: str = ""
    files_read: list[str] | None = None
    confirmation_scope: str = ""
    raw_reply: str = ""


# Per-request context: isolates active thread/trace/parent across concurrent
# reply() calls. FastAPI runs sync endpoints in a threadpool where each task
# gets its own copied context, so concurrent conversations don't clobber
# each other's state.
_active_thread_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "active_thread_id", default="",
)
_active_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "active_trace_id", default="",
)
_active_parent_message_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "active_parent_message_id", default="",
)


class ChatService:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        profile_service: ProfileService,
        skill_manager: SkillManager,
        agent_config_store: AgentConfigStore | None = None,
        sync_service: SyncService | None = None,
        file_auth: FileAuthService | None = None,
        mcp_manager: McpManager | None = None,
        shibei_service: ShibeiService | None = None,
        session_store: SessionStore | None = None,
        turn_runner: TurnRunner | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._profile_service = profile_service
        self._skills = skill_manager
        self._agent_config_store = agent_config_store
        self._sync_service = sync_service
        self._file_auth = file_auth or FileAuthService(
            settings.resolved_data_dir() / "file_auth.json",
        )
        self._history_path = settings.resolved_data_dir() / "chat_history.json"
        self._memory = LuminaMemory(settings.resolved_data_dir())
        self._background_review = BackgroundReviewService(
            self._memory,
            profile_service=self._profile_service,
        )
        self._exec_skills = ExecutableSkillManager(settings.resolved_data_dir())
        # F21: Reflexion — failure-triggered reflection memory
        self._reflection_trigger = ReflectionTrigger(max_steps=20)
        self._reflection_runner: ReflectionRunner | None = None
        self._pending: PendingConfirmation | None = None
        self._pending_messages: list[dict[str, str]] | None = None
        self._pending_llm_config: LlmConfig | None = None
        self._pending_lock = threading.Lock()
        self._subagent_pending: SubAgentResumeState | None = None
        self._parent_turn_resume: ParentTurnResumeState | None = None
        self._active_spawn_tool: SpawnSubagentTool | None = None
        self._prompt_gate = PromptGate(settings, agent_config_store)
        from secretary.agent.web_routing import WebIntentRouter

        self._web_intent_router = WebIntentRouter(settings, agent_config_store)
        self._split_checked_threads: set[str] = set()
        self._history_lock = threading.Lock()
        self._history_cache: list[dict[str, str]] | None = None
        self._history_cache_time: float = 0.0
        self._system_prompt_cache: str | None = None
        self._system_prompt_cache_key: str = ""
        self._session_store = session_store or SessionStore()
        try:
            self._session_store.prune_stale()
        except Exception:
            logger.debug("SessionStore prune skipped", exc_info=True)
        self._turn_runner = turn_runner or TurnRunner(
            self._file_auth,
            hooks_factory=self._build_loop_hooks,
            session_store=self._session_store,
        )
        self._mcp_manager = mcp_manager
        self._shibei_service = shibei_service
        self._thread_store = ChatThreadStore(settings.resolved_data_dir() / "chat_threads.json")
        self._active_thread_id = ""
        self._active_trace_id = ""
        self._active_parent_message_id = ""
        self._turn_working_dir: Path | None = None
        self._tool_registry = ChatToolRegistry(
            settings=settings,
            store=store,
            memory=self._memory,
            skills=skill_manager,
            file_auth=self._file_auth,
            mcp_manager=mcp_manager,
            shibei_service=shibei_service,
            sync_service=sync_service,
            get_session_id=self._get_or_create_session_id,
            shell_working_dir=self._shell_working_dir,
            temperature=self._temperature,
        )

    def _ensure_reflection_runner(self, llm_config: LlmConfig) -> ReflectionRunner:
        """F21: Lazily create ReflectionRunner with current llm_config."""
        if self._reflection_runner is None:
            self._reflection_runner = ReflectionRunner(
                llm_config=llm_config,
                file_auth=self._file_auth,
                memory_store=self._store,
                memory=self._memory,
                lumina_dir=self._settings.resolved_data_dir(),
            )
        return self._reflection_runner

    @property
    def memory(self) -> LuminaMemory:
        return self._memory

    @property
    def exec_skills(self) -> ExecutableSkillManager:
        return self._exec_skills

    @property
    def pending_confirmation(self) -> PendingConfirmation | None:
        with self._pending_lock:
            return self._pending

    def _take_pending(self) -> tuple[PendingConfirmation | None, list[dict[str, str]] | None, LlmConfig | None]:
        """Atomically take and clear the pending confirmation state."""
        with self._pending_lock:
            pending = self._pending
            messages = self._pending_messages
            llm_config = self._pending_llm_config
            self._pending = None
            self._pending_messages = None
            self._pending_llm_config = None
            return pending, messages, llm_config

    def _persist_pause(self, trace_id: str, kind: PauseKind, data: dict[str, Any]) -> None:
        if not trace_id or self._session_store.persistence_path is None:
            return
        self._session_store.save_pause(trace_id, kind=kind, data=data)
        self._session_store.update_turn_status(trace_id, status="paused")

    def _clear_persisted_pause(self, trace_id: str) -> None:
        if trace_id:
            self._session_store.clear_pause(trace_id)

    def _restore_pause_from_store(self, trace_id: str) -> None:
        if not trace_id or self._session_store.persistence_path is None:
            return
        loaded = self._session_store.load_pauses(trace_id)
        if not loaded:
            return
        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        if llm_config is None:
            return
        sub_state = None
        if "confirmation" in loaded:
            try:
                pending, messages = pause_restore_confirmation(loaded["confirmation"])
                self._set_pending(pending, messages, llm_config, persist=False)
            except ValueError as exc:
                logger.warning("confirmation pause restore failed: %s", exc)
        if "subagent" in loaded:
            try:
                sub_state = pause_restore_subagent(loaded["subagent"], llm_config)
                self._handle_subagent_paused(sub_state, persist=False)
            except ValueError as exc:
                logger.warning("subagent pause restore failed: %s", exc)
        if "parent_resume" in loaded:
            try:
                tools = self._tool_registry.build_tools()
                self._set_parent_turn_resume(
                    pause_restore_parent(
                        loaded["parent_resume"],
                        llm_config=llm_config,
                        tools=tools,
                    ),
                    persist=False,
                )
            except ValueError as exc:
                logger.warning("parent resume pause restore failed: %s", exc)
        if sub_state is not None or self._parent_turn_resume is not None:
            parent_session_id = (
                sub_state.parent_session_id if sub_state is not None else ""
            )
            self._active_spawn_tool = self._tool_registry.make_spawn_tool(
                llm_config,
                parent_session_id=parent_session_id or None,
            )

    def _set_pending(
        self,
        pending: PendingConfirmation,
        messages: list[dict[str, str]],
        llm_config: LlmConfig,
        *,
        persist: bool = True,
    ) -> None:
        """Atomically set the pending confirmation state."""
        with self._pending_lock:
            self._pending = pending
            self._pending_messages = messages
            self._pending_llm_config = llm_config
        if persist:
            self._persist_pause(
                _active_trace_id_var.get(),
                "confirmation",
                pause_bundle_confirmation(pending=pending, messages=messages),
            )

    def _handle_subagent_paused(self, state: SubAgentResumeState, *, persist: bool = True) -> None:
        with self._pending_lock:
            self._subagent_pending = state
        if persist:
            self._persist_pause(_active_trace_id_var.get(), "subagent", pause_bundle_subagent(state))

    def _take_subagent_pending(self) -> SubAgentResumeState | None:
        with self._pending_lock:
            state = self._subagent_pending
            self._subagent_pending = None
            return state

    def _set_parent_turn_resume(self, state: ParentTurnResumeState, *, persist: bool = True) -> None:
        with self._pending_lock:
            self._parent_turn_resume = state
        if persist:
            self._persist_pause(_active_trace_id_var.get(), "parent_resume", pause_bundle_parent(state))

    def _take_parent_turn_resume(self) -> ParentTurnResumeState | None:
        with self._pending_lock:
            state = self._parent_turn_resume
            self._parent_turn_resume = None
            return state

    def is_author_turn(self, message: str) -> bool:
        cleaned = message.strip()
        if not cleaned:
            return False
        return is_author_request(cleaned)

    def is_identity_turn(self, message: str) -> bool:
        cleaned = message.strip()
        if not cleaned:
            return False
        return is_identity_request(cleaned, self._load_history())

    @property
    def session_store(self) -> SessionStore:
        return self._session_store

    @property
    def _turn_orchestrator(self) -> TurnRunner:
        """Backward-compatible access for tests patching the inner runner."""
        return self._turn_runner

    def _active_turn(self, trace_id: str | None) -> TurnContext | None:
        if not trace_id:
            return None
        return self._session_store.get_turn(trace_id)

    def reply(
        self,
        message: str,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
        parent_message_id: str | None = None,
        working_dir: str | None = None,
        attachments: list[str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ChatResult:
        cleaned = message.strip()
        self._active_thread_id = thread_id.strip() if thread_id else ""
        self._active_trace_id = trace_id.strip() if trace_id else ""
        self._active_parent_message_id = parent_message_id or ""
        self._turn_working_dir = self._resolve_turn_working_dir(working_dir)
        _active_thread_id_var.set(self._active_thread_id)
        _active_trace_id_var.set(self._active_trace_id)
        _active_parent_message_id_var.set(self._active_parent_message_id)
        if attachments:
            from secretary.services.chat_uploads import format_attachments_block

            block = format_attachments_block(attachments)
            if block:
                cleaned = f"{cleaned}\n\n{block}" if cleaned else block
        history = self._load_history()
        if is_author_request(cleaned):
            return self._handle_author_gate(cleaned)
        if is_identity_request(cleaned, history):
            return self._handle_identity_gate(cleaned)

        from secretary.agent.project_author import (
            is_project_author_question,
            lookup_project_author,
        )

        if is_project_author_question(cleaned):
            fast = lookup_project_author(cleaned, self._shell_working_dir())
            if fast:
                return self._finish_gate_reply(
                    cleaned,
                    fast,
                    used_llm=False,
                    used_tools=["file_read"],
                    grounding_verified=True,
                )

        web_plan = resolve_web_search_with_llm_fallback(
            cleaned,
            history,
            llm_router=self._web_intent_router
            if self._settings.web_intent_router_enabled
            else None,
        )
        if web_plan is not None:
            llm_config = resolve_llm_config(self._settings, self._agent_config_store)
            if llm_config is None:
                return self._finish_gate_reply(
                    cleaned,
                    "还没配置大模型，暂时无法联网查询。",
                    used_llm=False,
                )
            view = self._profile_service.get_view()
            hits = self._store.search(cleaned, limit=5)
            return self._run_web_agent_turn(
                cleaned,
                web_plan,
                view.markdown,
                hits,
                llm_config,
                view.markdown[:800],
                memory_hits=len(hits),
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        decision = self._prompt_gate.evaluate(cleaned, history)

        if decision.action == GateAction.REJECT:
            return self._finish_gate_reply(
                cleaned,
                "这个请求我没法帮你处理。",
                used_llm=False,
            )
        if decision.action == GateAction.SYNC:
            return self._handle_sync_gate(cleaned)
        if decision.action == GateAction.PROFILE:
            return self._handle_profile_gate(cleaned)
        if decision.action == GateAction.IDENTITY:
            return self._handle_identity_gate(cleaned)
        if decision.action == GateAction.CLARIFY:
            decision = GateDecision(action=GateAction.CONTINUE, intent=decision.intent)

        view = self._profile_service.get_view()
        hits = self._store.search(cleaned, limit=5)
        profile_excerpt = view.markdown[:800]

        from secretary.agent.sync_routing import resolve_sync_empty_reply

        sync_empty = resolve_sync_empty_reply(
            cleaned,
            self._store,
            self._sync_service,
            memory_hits=len(hits),
            shibei_service=self._shibei_service,
        )
        if sync_empty:
            return self._finish_gate_reply(
                cleaned,
                sync_empty,
                used_llm=False,
                route="sync_empty",
            )

        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        if llm_config is None:
            fallback = self._fallback_reply(cleaned, view.markdown, hits)
            self._append_history(cleaned, fallback)
            self._save_to_session("user", cleaned)
            self._save_to_session("assistant", fallback)
            return ChatResult(
                reply=fallback,
                profile_excerpt=profile_excerpt,
                used_llm=False,
                memory_hits=len(hits),
            )

        if decision.action == GateAction.DIRECT:
            from secretary.agent.grounding import (
                is_filesystem_question,
                is_personal_memory_question,
            )

            if is_filesystem_question(cleaned) or is_personal_memory_question(cleaned):
                decision = GateDecision(action=GateAction.CONTINUE, intent=decision.intent)
            else:
                return self._run_direct(
                    cleaned,
                    view.markdown,
                    hits,
                    llm_config,
                    profile_excerpt,
                    progress_callback=progress_callback,
                )

        return self._run_agent(
            cleaned,
            view.markdown,
            hits,
            llm_config,
            profile_excerpt,
            decision=decision,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    def confirm_action(
        self,
        approved: bool,
        *,
        grant_permanent_read: bool = False,
        grant_session_write: bool = False,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ChatResult:
        if thread_id:
            tid = thread_id.strip()
            self._active_thread_id = tid
            _active_thread_id_var.set(tid)
        _active_trace_id_var.set(trace_id.strip() if trace_id else "")
        self._active_trace_id = _active_trace_id_var.get()
        _active_parent_message_id_var.set("")
        self._active_parent_message_id = ""
        self._restore_pause_from_store(_active_trace_id_var.get())
        sub_state = self._take_subagent_pending()
        pending, messages, llm_config = self._take_pending()
        with self._pending_lock:
            spawn_tool = self._active_spawn_tool

        if not approved or pending is None or messages is None or llm_config is None:
            reply = "好的，已取消操作。"
            # Stale confirm (no pending): never invent a fake "system" user turn —
            # that was creating empty threads titled "system" on deny/restart races.
            if pending is not None:
                self._append_assistant_notice(reply)
            self._clear_persisted_pause(_active_trace_id_var.get())
            return ChatResult(
                reply=reply,
                profile_excerpt="",
                used_llm=False,
                memory_hits=0,
            )

        if grant_permanent_read:
            self._file_auth.grant_permanent_read()
        if grant_session_write:
            self._file_auth.grant_session_write_new()

        if sub_state is not None:
            if spawn_tool is None:
                self._clear_persisted_pause(_active_trace_id_var.get())
                reply = "子代理状态丢失，无法恢复。请重新发起请求。"
                self._append_assistant_notice(reply)
                return ChatResult(
                    reply=reply,
                    profile_excerpt="",
                    used_llm=False,
                    memory_hits=0,
                )
            return self._confirm_subagent_action(
                sub_state,
                spawn_tool,
                messages,
                llm_config,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        tools = self._tool_registry.build_tools()
        result = self._turn_runner.run_confirmed_action(
            llm_config,
            tools,
            pending,
            messages,
            temperature=0.7,
            working_dir=self._shell_working_dir(),
            progress_callback=progress_callback,
            turn=self._active_turn(_active_trace_id_var.get()),
            cancel_check=cancel_check,
        )

        if result.pending_confirmation:
            self._set_pending(
                result.pending_confirmation,
                messages + [{"role": "assistant", "content": result.reply}],
                llm_config,
            )

        if result.pending_confirmation is None:
            self._clear_persisted_pause(_active_trace_id_var.get())

        safe_reply, _, _ = self._prepare_user_reply(
            result.reply,
            "system:confirmed",
            llm_config,
            used_tools=result.used_tools,
            grounding_verified=result.grounding_verified,
            grounding_note=result.grounding_note,
        )
        self._append_history("system:confirmed", safe_reply)
        self._save_to_session("assistant", safe_reply)

        cui = _confirmation_ui(result.pending_confirmation)
        return ChatResult(
            reply=safe_reply,
            profile_excerpt="",
            used_llm=True,
            memory_hits=0,
            used_tools=result.used_tools,
            total_steps=result.total_steps,
            pending_confirmation=result.pending_confirmation,
            confirmation_kind=cui.confirmation_kind,
            allow_permanent_read=cui.allow_permanent_read,
            allow_session_write=cui.allow_session_write,
        )

    def _confirm_subagent_action(
        self,
        state: SubAgentResumeState,
        spawn_tool: SpawnSubagentTool,
        messages: list[dict[str, str]],
        llm_config: LlmConfig,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ChatResult:
        summary = spawn_tool._runner.resume_paused(
            state,
            self._shell_working_dir(),
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        re_paused = spawn_tool.consume_paused()
        if re_paused is not None:
            self._handle_subagent_paused(re_paused)
            raw_reply = (
                f"子 Agent ({re_paused.archetype}) 需要你的确认：\n\n"
                f"{re_paused.pending.description}\n\n是否允许？"
            )
            self._set_pending(
                re_paused.pending,
                messages + [{"role": "assistant", "content": raw_reply}],
                llm_config,
            )
            safe_reply, _, _ = self._prepare_user_reply(raw_reply, "system:confirmed", llm_config)
            self._append_history("system:confirmed", safe_reply)
            self._save_to_session("assistant", safe_reply)
            cui = _confirmation_ui(re_paused.pending)
            return ChatResult(
                reply=safe_reply,
                profile_excerpt="",
                used_llm=True,
                memory_hits=0,
                pending_confirmation=re_paused.pending,
                confirmation_kind=cui.confirmation_kind,
                allow_permanent_read=cui.allow_permanent_read,
                allow_session_write=cui.allow_session_write,
                confirmation_scope="subagent",
            )

        parent_resume = self._take_parent_turn_resume()
        if parent_resume is not None:
            result = self._turn_runner.resume_after_subagent(
                llm_config,
                parent_resume,
                summary,
                temperature=self._temperature(),
                working_dir=self._shell_working_dir(),
                progress_callback=progress_callback,
                on_subagent_paused=self._handle_subagent_paused,
                turn=self._active_turn(_active_trace_id_var.get()),
                cancel_check=cancel_check,
            )
            if (
                result.pending_confirmation
                and self._subagent_pending
                and result.messages_snapshot
                and result.pending_step
            ):
                self._set_parent_turn_resume(
                    ParentTurnResumeState(
                        messages_snapshot=list(result.messages_snapshot),
                        tools=parent_resume.tools,
                        max_steps=parent_resume.max_steps,
                        pending_step=result.pending_step,
                        assistant_message=result.pause_assistant_message,
                        native_used=result.pause_native_used,
                        step_idx=result.total_steps - 1,
                        llm_config=llm_config,
                        session_id=parent_resume.session_id,
                        user_message=parent_resume.user_message,
                        profile_excerpt=parent_resume.profile_excerpt,
                        memory_hits=parent_resume.memory_hits,
                    )
                )
            return self._finalize_agent_result(
                parent_resume.user_message,
                parent_resume.messages_snapshot,
                result,
                llm_config,
                parent_resume.session_id,
                parent_resume.profile_excerpt,
                memory_hits=parent_resume.memory_hits,
            )

        raw_reply = f"子 Agent ({state.archetype}) 已完成：\n\n{summary}"
        safe_reply, _, _ = self._prepare_user_reply(raw_reply, "system:confirmed", llm_config)
        self._append_history("system:confirmed", safe_reply)
        self._save_to_session("assistant", safe_reply)
        self._background_review.schedule("system:confirmed", safe_reply, llm_config)
        return ChatResult(
            reply=safe_reply,
            profile_excerpt="",
            used_llm=True,
            memory_hits=0,
            confirmation_scope="subagent",
        )

    def clear_history(self) -> None:
        if self._history_path.exists():
            self._history_path.unlink()

    def _finish_gate_reply(
        self,
        user_message: str,
        reply: str,
        *,
        used_llm: bool,
        profile_excerpt: str = "",
        memory_hits: int = 0,
        used_tools: list[str] | None = None,
        grounding_verified: bool = True,
        route: str = "",
    ) -> ChatResult:
        tools = list(used_tools or [])
        if route == "sync_empty":
            safe_reply = prepare_user_facing_reply(reply, user_message, None)
            verified, note = True, ""
        else:
            safe_reply, verified, note = self._prepare_user_reply(
                reply,
                user_message,
                None,
                used_tools=tools,
                grounding_verified=grounding_verified,
            )
        self._append_history(user_message, safe_reply)
        self._save_to_session("user", user_message)
        self._save_to_session("assistant", safe_reply)
        return ChatResult(
            reply=safe_reply,
            profile_excerpt=profile_excerpt,
            used_llm=used_llm,
            memory_hits=memory_hits,
            used_tools=tools or None,
            grounding_verified=verified,
            grounding_note=note,
            route=route,
        )

    def _handle_sync_gate(self, user_message: str) -> ChatResult:
        if self._sync_service is None:
            return self._finish_gate_reply(
                user_message,
                "同步服务不可用，请稍后重试。",
                used_llm=False,
            )
        results = self._sync_service.sync_all(include_browser_sources=True)
        inserted = sum(item.inserted for item in results)
        reply = f"同步完成，写入 {inserted} 条记忆。"
        return self._finish_gate_reply(user_message, reply, used_llm=False)

    def _handle_profile_gate(self, user_message: str) -> ChatResult:
        view = self._profile_service.get_view()
        profile = view.markdown.strip() or "暂无个人画像。可以点击右上角「同步」导入你的数据。"
        return self._finish_gate_reply(
            user_message,
            profile,
            used_llm=False,
            profile_excerpt=profile[:800],
        )

    def _handle_author_gate(self, user_message: str) -> ChatResult:
        reply = get_author_reply()
        self._append_history(user_message, reply)
        self._save_to_session("user", user_message)
        self._save_to_session("assistant", reply)
        return ChatResult(
            reply=reply,
            profile_excerpt="",
            used_llm=False,
            memory_hits=0,
            total_steps=0,
            route="author",
        )

    def _handle_identity_gate(self, user_message: str) -> ChatResult:
        reply = get_identity_reply()
        self._append_history(user_message, reply)
        self._save_to_session("user", user_message)
        self._save_to_session("assistant", reply)
        return ChatResult(
            reply=reply,
            profile_excerpt="",
            used_llm=False,
            memory_hits=0,
            total_steps=0,
            route="identity",
        )

    def _run_direct(
        self,
        cleaned: str,
        profile_markdown: str,
        hits: list[MemoryChunk],
        llm_config: LlmConfig,
        profile_excerpt: str,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> ChatResult:
        system_prompt = self._build_system_prompt(profile_markdown, hits, user_message=cleaned)
        session_id = self._get_or_create_session_id()
        self._memory.create_session(session_id)
        self._save_to_session("user", cleaned)

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    system_prompt
                    + "\n\n直接回答用户，不要调用工具。"
                    + "不要输出思考过程、推理链或 think 标签；给最终答案即可。"
                ),
            },
        ]
        messages.extend(self._load_history())
        messages.append({"role": "user", "content": cleaned})

        try:
            stream_started = False

            def on_delta(delta: str) -> None:
                nonlocal stream_started
                if progress_callback is None or not delta:
                    return
                if not stream_started:
                    progress_callback(ProgressEvent(kind="reply_start", iteration=1))
                    stream_started = True
                progress_callback(
                    ProgressEvent(kind="reply_delta", iteration=1, message=delta)
                )

            reply = chat_completion(
                llm_config,
                messages,
                temperature=self._temperature(),
                timeout=120.0,
                on_delta=on_delta if progress_callback else None,
            )
            if progress_callback and stream_started:
                progress_callback(ProgressEvent(kind="reply_end", iteration=1))
            raw_reply = reply
            reply, verified, note = self._prepare_user_reply(raw_reply, cleaned, llm_config)
            self._memory.end_session(session_id, summary=reply[:200])
            self._append_history(cleaned, reply)
            self._save_to_session("assistant", reply)
            self._background_review.schedule(cleaned, reply, llm_config)
            return ChatResult(
                reply=reply,
                raw_reply=raw_reply,
                profile_excerpt=profile_excerpt,
                used_llm=True,
                memory_hits=len(hits),
                total_steps=1,
                grounding_verified=verified,
                grounding_note=note,
            )
        except AgentError as error:
            fallback = (
                f"{error}\n\n"
                "我先切换到离线模式：\n"
                f"{self._fallback_reply(cleaned, profile_markdown, hits, llm_configured=True)}"
            )
            self._append_history(cleaned, fallback)
            self._save_to_session("assistant", fallback)
            return ChatResult(
                reply=fallback,
                profile_excerpt=profile_excerpt,
                used_llm=False,
                memory_hits=len(hits),
            )
        except Exception as exc:
            logger.exception("Unexpected error in chat turn")
            fallback = (
                f"抱歉，处理请求时出错（{type(exc).__name__}）。\n\n"
                f"{self._fallback_reply(cleaned, profile_markdown, hits, llm_configured=True)}"
            )
            self._append_history(cleaned, fallback)
            self._save_to_session("assistant", fallback)
            return ChatResult(
                reply=fallback,
                profile_excerpt=profile_excerpt,
                used_llm=False,
                memory_hits=len(hits),
            )

    def _run_web_agent_turn(
        self,
        cleaned: str,
        plan: WebSearchPlan,
        profile_markdown: str,
        hits: list[MemoryChunk],
        llm_config: LlmConfig,
        profile_excerpt: str,
        *,
        memory_hits: int = 0,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ChatResult:
        """Realtime/web queries: agent loop with web_search + web_fetch (model picks tools)."""
        from secretary.agent.web_research import WEB_RESEARCH_APPENDIX

        session_id = self._get_or_create_session_id()
        self._memory.create_session(session_id)
        self._save_to_session("user", cleaned)

        from secretary.agent.browser_tools import agent_browser_available
        from secretary.agent.web_research import BROWSER_TOOL_GUIDANCE

        appendix = WEB_RESEARCH_APPENDIX
        if agent_browser_available():
            appendix += "\n\n" + BROWSER_TOOL_GUIDANCE
        if plan.search_query.strip() != cleaned.strip():
            appendix += f"\n- 若首轮检索不佳，可尝试关键词：{plan.search_query}"

        system_prompt = self._build_system_prompt(profile_markdown, hits, user_message=cleaned) + "\n\n" + appendix
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(self._load_history())
        messages.append({"role": "user", "content": cleaned})

        tools = self._pick_web_tools(cleaned)
        agent_plan = AgentTurnPlan(messages=messages, max_steps=20, tools=tools)

        if progress_callback is not None:
            progress_callback(
                ProgressEvent(
                    kind="iteration_started",
                    iteration=1,
                    message="网络连接 · 开始联网检索",
                )
            )

        try:
            result = self._turn_runner.run_agent_turn(
                llm_config,
                agent_plan,
                temperature=self._temperature(),
                working_dir=self._shell_working_dir(),
                progress_callback=progress_callback,
                turn=self._active_turn(_active_trace_id_var.get()),
                cancel_check=cancel_check,
            )
            chat = self._finalize_agent_result(
                cleaned,
                messages,
                result,
                llm_config,
                session_id,
                profile_excerpt,
                memory_hits=memory_hits,
            )
            return ChatResult(
                reply=chat.reply,
                profile_excerpt=chat.profile_excerpt,
                used_llm=chat.used_llm,
                memory_hits=chat.memory_hits,
                used_tools=chat.used_tools,
                total_steps=chat.total_steps,
                pending_confirmation=chat.pending_confirmation,
                grounding_verified=chat.grounding_verified,
                grounding_note=chat.grounding_note,
                route="web_agent",
            )
        except AgentError as error:
            fallback = f"{error}\n\n请稍后重试，或把问题收窄（例如指定平台/语言/时间范围）。"
            self._append_history(cleaned, fallback)
            self._save_to_session("assistant", fallback)
            return ChatResult(
                reply=fallback,
                profile_excerpt=profile_excerpt,
                used_llm=False,
                memory_hits=memory_hits,
                route="web_agent",
            )

    def _run_agent(
        self,
        cleaned: str,
        profile_markdown: str,
        hits: list[MemoryChunk],
        llm_config: LlmConfig,
        profile_excerpt: str,
        *,
        decision: GateDecision,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ChatResult:
        configured = self._current_agent_profile()
        light_mode = decision.action == GateAction.LIGHT
        from secretary.agent.grounding import is_filesystem_question

        filesystem_turn = is_filesystem_question(cleaned)
        profile = effective_profile(
            configured,
            cleaned,
            light_mode=light_mode,
            filesystem_turn=filesystem_turn,
        )
        system_prompt = (
            self._build_system_prompt(profile_markdown, hits, user_message=cleaned)
            + profile_system_appendix(profile)
        )
        session_id = self._get_or_create_session_id()
        self._memory.create_session(session_id)
        self._save_to_session("user", cleaned)

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(self._load_history())
        messages.append({"role": "user", "content": cleaned})

        forced_shell_command = _extract_forced_shell_command(cleaned)
        if forced_shell_command is not None:
            action_id = f"act_{datetime.now(UTC).strftime('%H%M%S')}_shell"
            pending = PendingConfirmation(
                action_id=action_id,
                tool_name="shell",
                arguments={"command": forced_shell_command},
                description=f"⚡ 执行命令: `{forced_shell_command}`",
                risk_level="high",
                confirmation_kind="shell",
            )
            self._set_pending(pending, messages, llm_config)
            raw_reply = (
                "我需要你的确认才能继续：\n\n"
                f"⚡ 执行命令: `{forced_shell_command}`\n\n"
                "是否允许？"
            )
            safe_reply, _, _ = self._prepare_user_reply(raw_reply, cleaned, llm_config)
            self._append_history(cleaned, safe_reply)
            self._save_to_session("assistant", safe_reply)
            cui2 = _confirmation_ui(pending)
            return ChatResult(
                reply=safe_reply,
                profile_excerpt=profile_excerpt,
                used_llm=True,
                memory_hits=len(hits),
                used_tools=[],
                total_steps=1,
                pending_confirmation=pending,
                confirmation_kind=cui2.confirmation_kind,
                allow_permanent_read=cui2.allow_permanent_read,
                allow_session_write=cui2.allow_session_write,
            )

        light_mode = decision.action == GateAction.LIGHT
        suggested = decision.intent.suggested_tools if decision.intent else ()
        tools, spawn_tool = self._tool_registry.resolve_tools(
            profile=profile,
            user_message=cleaned,
            suggested=suggested,
            filesystem_turn=filesystem_turn,
            light_mode=light_mode,
            llm_config=llm_config,
        )
        with self._pending_lock:
            self._active_spawn_tool = spawn_tool if isinstance(spawn_tool, SpawnSubagentTool) else None

        if profile is AgentProfile.PLAN:
            max_steps = default_max_steps_for_profile(profile, filesystem_turn=filesystem_turn)
        elif profile is AgentProfile.ASK:
            max_steps = default_max_steps_for_profile(profile, filesystem_turn=filesystem_turn)
        elif filesystem_turn:
            max_steps = default_max_steps_for_profile(AgentProfile.BUILD, filesystem_turn=True)
        elif light_mode:
            max_steps = 3
        else:
            max_steps = default_max_steps_for_profile(AgentProfile.BUILD, filesystem_turn=False)

        plan = AgentTurnPlan(messages=messages, max_steps=max_steps, tools=tools)

        try:
            result = self._turn_runner.run_agent_turn(
                llm_config,
                plan,
                temperature=self._temperature(),
                working_dir=self._shell_working_dir(),
                progress_callback=progress_callback,
                on_subagent_paused=self._handle_subagent_paused,
                turn=self._active_turn(_active_trace_id_var.get()),
                cancel_check=cancel_check,
            )
            if (
                result.pending_confirmation
                and self._subagent_pending
                and result.messages_snapshot
                and result.pending_step
            ):
                self._set_parent_turn_resume(
                    ParentTurnResumeState(
                        messages_snapshot=list(result.messages_snapshot),
                        tools=plan.tools,
                        max_steps=plan.max_steps,
                        pending_step=result.pending_step,
                        assistant_message=result.pause_assistant_message,
                        native_used=result.pause_native_used,
                        step_idx=result.total_steps - 1,
                        llm_config=llm_config,
                        session_id=session_id,
                        user_message=cleaned,
                        profile_excerpt=profile_excerpt,
                        memory_hits=len(hits),
                    )
                )
            return self._finalize_agent_result(
                cleaned,
                messages,
                result,
                llm_config,
                session_id,
                profile_excerpt,
                memory_hits=len(hits),
            )
        except AgentError as error:
            fallback = (
                f"{error}\n\n"
                "我先切换到离线模式：\n"
                f"{self._fallback_reply(cleaned, profile_markdown, hits, llm_configured=True)}"
            )
            self._append_history(cleaned, fallback)
            self._save_to_session("assistant", fallback)
            return ChatResult(
                reply=fallback,
                profile_excerpt=profile_excerpt,
                used_llm=False,
                memory_hits=len(hits),
            )
        except Exception as exc:
            logger.exception("Unexpected error in chat turn")
            fallback = (
                f"抱歉，处理请求时出错（{type(exc).__name__}）。\n\n"
                f"{self._fallback_reply(cleaned, profile_markdown, hits, llm_configured=True)}"
            )
            self._append_history(cleaned, fallback)
            self._save_to_session("assistant", fallback)
            return ChatResult(
                reply=fallback,
                profile_excerpt=profile_excerpt,
                used_llm=False,
                memory_hits=len(hits),
            )

    def _finalize_agent_result(
        self,
        cleaned: str,
        messages: list[dict[str, str]],
        result: LoopResult,
        llm_config: LlmConfig,
        session_id: str,
        profile_excerpt: str,
        *,
        memory_hits: int,
    ) -> ChatResult:
        raw_reply = result.reply
        safe_reply, grounding_verified, grounding_note = self._prepare_user_reply(
            raw_reply,
            cleaned,
            llm_config,
            used_tools=result.used_tools,
            grounding_verified=result.grounding_verified,
            grounding_note=result.grounding_note,
        )

        if result.pending_confirmation:
            self._set_pending(
                result.pending_confirmation,
                messages + [{"role": "assistant", "content": safe_reply}],
                llm_config,
            )

        self._memory.end_session(session_id, summary=safe_reply[:200])

        if result.used_tools:
            episode_id = str(uuid.uuid4())[:8]
            steps_data = [
                {
                    "thought": s.thought[:200],
                    "tool": s.tool_call.name if s.tool_call else "",
                    "output": (s.tool_output or "")[:200],
                }
                for s in result.steps
            ]
            episode_success = (
                result.grounding_verified
                and not result.cancelled
                and result.total_steps < self._reflection_trigger._max_steps
            )
            self._memory.save_episode(
                episode_id=episode_id,
                task=cleaned[:500],
                steps=steps_data,
                result=safe_reply[:2000],
                success=episode_success,
                tools_used=result.used_tools,
            )

        # F21: Trigger reflection on Build-profile failures (non-blocking)
        if (
            not result.pending_confirmation
            and result.used_tools
            and "build" in (profile_excerpt or "").lower()
        ):
            self._maybe_trigger_reflection(
                signal_user_message=cleaned,
                raw_reply=raw_reply,
                loop_result=result,
                turn_status="cancelled" if result.cancelled else "completed",
                llm_config=llm_config,
                thread_id=self._active_thread_id,
            )

        self._append_history(cleaned, safe_reply)
        self._save_to_session("assistant", safe_reply)

        if result.pending_confirmation is None:
            self._background_review.schedule(cleaned, safe_reply, llm_config)

        cui3 = _confirmation_ui(result.pending_confirmation)
        confirmation_scope = ""
        if result.pending_confirmation is not None and self._subagent_pending is not None:
            confirmation_scope = "subagent"
        return ChatResult(
            reply=safe_reply,
            profile_excerpt=profile_excerpt,
            used_llm=True,
            memory_hits=memory_hits,
            used_tools=result.used_tools,
            total_steps=result.total_steps,
            pending_confirmation=result.pending_confirmation,
            confirmation_kind=cui3.confirmation_kind,
            allow_permanent_read=cui3.allow_permanent_read,
            allow_session_write=cui3.allow_session_write,
            grounding_verified=grounding_verified,
            grounding_note=grounding_note,
            files_read=result.files_read or None,
            confirmation_scope=confirmation_scope,
            raw_reply=raw_reply,
        )

    def _maybe_trigger_reflection(
        self,
        *,
        signal_user_message: str,
        raw_reply: str,
        loop_result: LoopResult,
        turn_status: str,
        llm_config: LlmConfig,
        thread_id: str,
    ) -> None:
        """F21: Evaluate failure signals and trigger reflection if matched."""
        tool_call_history = self._extract_tool_call_history(loop_result)
        signal = self._reflection_trigger.evaluate(
            profile="build",
            user_message=signal_user_message,
            raw_reply=raw_reply,
            loop_result=loop_result,
            turn_status=turn_status,
            tool_call_history=tool_call_history,
        )
        if signal is None:
            return
        try:
            runner = self._ensure_reflection_runner(llm_config)
            working_dir = self._turn_working_dir or Path.cwd()
            reflection_json = runner.run(
                signal,
                working_dir=working_dir,
                parent_session_id=self._get_or_create_session_id(),
            )
            if not reflection_json:
                logger.debug("Reflection produced no output for mode=%s", signal.mode)
                return
            reflection_episode_id = f"refl_{uuid.uuid4().hex[:8]}"
            self._memory.save_episode(
                episode_id=reflection_episode_id,
                task=signal_user_message[:500],
                steps=[],
                result=raw_reply[:2000],
                success=False,
                tools_used=loop_result.used_tools,
                failure_mode=signal.mode,
                reflection_text=reflection_json,
                thread_id=thread_id or None,
            )
            logger.info("Reflection saved: mode=%s, episode=%s", signal.mode, reflection_episode_id)
        except Exception as exc:
            logger.warning("Reflection failed (non-blocking): %s", exc)

    @staticmethod
    def _extract_tool_call_history(result: LoopResult) -> list[dict[str, Any]]:
        """Extract tool call summaries from LoopResult for reflection trigger."""
        history: list[dict[str, Any]] = []
        for step in result.steps:
            if step.tool_call is None:
                continue
            history.append({
                "name": step.tool_call.name,
                "arguments": step.tool_call.arguments if hasattr(step.tool_call, "arguments") else {},
                "output": (step.tool_output or "")[:500],
            })
        return history

    def _prepare_user_reply(
        self,
        raw_reply: str,
        user_message: str,
        llm_config: LlmConfig | None,
        *,
        used_tools: list[str] | None = None,
        grounding_verified: bool = True,
        grounding_note: str = "",
    ) -> tuple[str, bool, str]:
        from secretary.agent.grounding import enforce_grounded_reply

        if is_user_input_request(raw_reply):
            return raw_reply, grounding_verified, grounding_note

        from secretary.agent.structured_cards import is_structured_card_output

        if is_structured_card_output(raw_reply):
            return raw_reply, grounding_verified, grounding_note

        sanitized = prepare_user_facing_reply(raw_reply, user_message, llm_config)
        reply, verified, note = enforce_grounded_reply(
            sanitized,
            user_message,
            list(used_tools or []),
            grounding_verified=grounding_verified,
            grounding_note=grounding_note,
        )
        return self._structure_reply(reply), verified, note

    @staticmethod
    def _structure_reply(reply: str) -> str:
        """对最终回复做确定性的结构化兜底（不依赖 LLM 自觉）。"""
        import re

        if not reply:
            return reply
        # 压缩 3+ 连续换行为 2
        reply = re.sub(r"\n{3,}", "\n\n", reply)
        # 行尾空白清理
        reply = "\n".join(line.rstrip() for line in reply.split("\n"))
        return reply

    def _temperature(self) -> float:
        if self._agent_config_store is not None:
            return self._agent_config_store.load().temperature
        return 0.7

    def _build_loop_hooks(self, tools: list[Tool]) -> LoopHookBundle:
        from secretary.agent.hook_policies import HooksConfig, build_default_hooks

        raw_hooks: dict[str, object] = {}
        if self._agent_config_store is not None:
            raw_hooks = dict(self._agent_config_store.load().hooks or {})
        config = HooksConfig.from_mapping(raw_hooks)
        profile = self._current_agent_profile()
        # Hooks run without a turn message; auto resolves to build (full tools).
        if profile is AgentProfile.AUTO:
            profile = AgentProfile.BUILD
        before, after = build_default_hooks(config, profile=profile, tools=tools)
        return LoopHookBundle(
            before_tool_execution=before,
            after_tool_execution=after,
        )

    def _resolve_turn_working_dir(self, working_dir: str | None) -> Path | None:
        raw = (working_dir or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if path.is_dir():
            return path.resolve()
        return None

    def _shell_working_dir(self) -> Path:
        if self._turn_working_dir is not None:
            return self._turn_working_dir
        raw = ""
        if self._agent_config_store is not None:
            raw = self._agent_config_store.load().shell_working_dir.strip()
        if raw:
            path = Path(raw).expanduser()
            if path.is_dir():
                return path.resolve()
        return Path.home()

    def _pick_web_tools(self, user_message: str) -> list[Tool]:
        from secretary.agent.tools.web import WebFetchTool
        from secretary.agent.web_search import WebSearchTool

        return self._tool_registry.append_browser_tools(
            [WebSearchTool(), WebFetchTool()],
            user_message,
        )

    def list_threads(self) -> dict[str, object]:
        # 加载对话历史时,自动检测并拆分每个线程内的断档链
        view = self._thread_store.list_view()
        threads = view.get("threads") or []
        changed = False
        for t in threads:
            tid = t.get("id", "") if isinstance(t, dict) else ""
            if not tid:
                continue
            if tid in self._split_checked_threads:
                continue
            result = self._thread_store.split_disconnected_chains(tid)
            if result.get("split_count", 0) > 0:
                changed = True
            self._split_checked_threads.add(tid)
        if changed:
            view = self._thread_store.list_view()
        return view

    def create_thread(self, *, title: str = "新对话") -> dict[str, object]:
        return self._thread_store.create_thread(title=title)

    def set_current_thread(self, thread_id: str) -> dict[str, object]:
        return self._thread_store.set_current(thread_id)

    def delete_thread(self, thread_id: str) -> dict[str, object]:
        return self._thread_store.delete_thread(thread_id)

    def save_threads(self, *, current_id: str, threads: list[dict[str, object]]) -> dict[str, object]:
        return self._thread_store.replace_all(current_id=current_id, threads=threads)

    def set_thread_active_leaf(self, thread_id: str, leaf_id: str) -> dict[str, object]:
        return self._thread_store.set_active_leaf(thread_id, leaf_id)

    def thread_tree(self, thread_id: str) -> dict[str, object]:
        return self._thread_store.thread_tree_view(thread_id)

    def rollback_thread(self, thread_id: str, to_message_id: str) -> dict[str, object]:
        return self._thread_store.rollback_to(thread_id, to_message_id)

    def restore_thread(self, thread_id: str, message_id: str) -> dict[str, object]:
        return self._thread_store.restore_archived(thread_id, message_id)

    def _current_agent_profile(self) -> AgentProfile:
        if self._agent_config_store is None:
            return AgentProfile.AUTO
        return parse_agent_profile(self._agent_config_store.load().agent_profile)

    def _build_reflections_block(self, user_message: str) -> str:
        """F21: Retrieve top-3 relevant failed-turn reflections and format for prompt."""
        if not user_message.strip():
            return ""
        try:
            episodes = self._memory.search_episodes(
                query=user_message,
                limit=3,
                success_only=False,
            )
        except Exception:
            return ""
        if not episodes:
            return ""

        lines = ["## 历史教训（按相关性检索，避免重蹈覆辙）"]
        for ep in episodes:
            refl_text = ep.get("reflection_text")
            if not refl_text:
                continue
            try:
                refl = json.loads(str(refl_text))
            except (json.JSONDecodeError, TypeError):
                continue
            summary = str(refl.get("failure_summary", ""))
            lesson = str(refl.get("lesson", ""))
            if not summary or summary == "non-informative":
                continue
            mode = ep.get("failure_mode") or "unknown"
            entry = f"- [{mode}] {summary} → {lesson[:120]}"
            lines.append(entry[:200])

        if len(lines) == 1:
            return ""
        return "\n".join(lines) + "\n\n"

    def _build_system_prompt(
        self, profile_markdown: str, hits: list[MemoryChunk], user_message: str = ""
    ) -> str:
        from secretary.agent.browser_tools import agent_browser_available
        from secretary.agent.web_research import BROWSER_TOOL_GUIDANCE

        soul = load_soul(self._settings.resolved_data_dir())
        skills = self._skills.prompt_block()
        exec_skills = self._exec_skills.prompt_block()

        # Cache the fixed prefix (soul + identity + skills + exec_skills)
        # based on content hash to avoid rebuilding on every call.
        cache_key = f"{soul}\x00{skills}\x00{exec_skills}"
        if self._system_prompt_cache_key == cache_key and self._system_prompt_cache is not None:
            prefix = self._system_prompt_cache
        else:
            prefix = (
                f"{soul}\n\n"
                f"{LUMINA_IDENTITY_SYSTEM_BLOCK}\n\n"
                "## 已安装技能\n"
                f"{skills}\n\n"
                "## 可执行技能\n"
                f"{exec_skills}\n\n"
            )
            self._system_prompt_cache = prefix
            self._system_prompt_cache_key = cache_key

        memory_block = self._format_memory_block(hits)
        profile_block = profile_markdown.strip() or "暂无个人画像。用户尚未同步数据源。"

        notes_path = self._settings.resolved_data_dir() / "NOTES.md"
        notes_block = ""
        if notes_path.exists():
            notes_text = notes_path.read_text(encoding="utf-8").strip()
            if notes_text:
                notes_block = f"\n\n## 持久笔记（跨会话保留，可用 notes 工具更新）\n{notes_text[:4000]}"

        memory_snapshot = self._memory.prompt_snapshot()
        memory_section = ""
        if memory_snapshot:
            memory_section = f"\n\n## Persistent Memory\n{memory_snapshot}"
        shibei_section = ""
        if self._shibei_service is not None and self._shibei_service.is_enabled():
            view = self._shibei_service.status_view()
            folders = "、".join(view.get("sources") or []) or "（未配置）"
            shibei_section = (
                "\n\n## Shibei 知识库（读取记忆的主路径）\n"
                "个人笔记、文档、面试资料等 **优先** 用 shibei_search 检索 Shibei 已有索引"
                "（config.yaml + ~/.shibei/db），**不需要** 先点 Lumina「同步」。\n"
                f"- 监控文件夹：{folders}\n"
                "- 检索为空时：shibei_import 增量导入，或在 Shibei 应用中 import\n"
                "- search_memory 仅查 Lumina 连接器同步库，作为 Shibei 的备选\n"
                "- 不要编造未出现在 shibei_search / search_memory 结果中的文档内容\n"
            )
        style_rule = (
            "- 语气档位：简短。先给结论，优先 1-3 句；只有必要时再补一句。\n"
            if self._response_style() == "brief"
            else f"- 语气档位：标准；在「{LUMINA_DEFAULT_STYLE}」基础上，先给结论，再补关键细节，避免啰嗦。\n"
        )
        format_rule = (
            "- 输出格式：长回答用 ## 分段；步骤用有序列表；命令、路径、文件名、变量名用 `行内代码`；"
            "代码块标注语言（```python / ```bash 等）；关键结论可用 > 引用块强调\n"
        )
        browser_rule = ""
        if agent_browser_available():
            browser_rule = (
                "- 静态页优先 web_fetch；JS 渲染/登录/榜单等用 browser_open → browser_snapshot → "
                "browser_click/browser_fill；完成后 browser_close\n"
            )

        reflections_block = self._build_reflections_block(user_message)

        return prefix + (
            "## 关于用户的资料（用户画像与本地文档，描述用户本人，不是灵犀）\n"
            f"{profile_block[:6000]}\n\n"
            "## 关于用户的本地记忆（用户经历与资料，不是灵犀的属性）\n"
            f"{memory_block}\n"
            f"{memory_section}"
            f"{shibei_section}"
            f"{notes_block}\n\n"
            f"{reflections_block}"
            "## 对话规则\n"
            "- 你是灵犀，用第二人称「你」跟用户说话；绝不用「用户」写第三方案情分析\n"
            "- 用户画像、本地文档、本地记忆说的是用户；灵犀的风格、技术栈、自我介绍只说灵犀自己的，二者不要混用\n"
            f"- 灵犀默认说话风格：{LUMINA_DEFAULT_STYLE}；先给结论，句子短，不铺垫、不堆砌\n"
            "- 回答里永远不要出现脏话、脏字、侮辱性表达或网络俚语（如「装逼」「扯淡」等）\n"
            "- 向用户介绍灵犀这个产品时，技术栈仅限 Electron + HTML/CSS/JS 前端与 Python + FastAPI 后端；"
            "不要把用户资料里的技术名词当成灵犀的技术栈；"
            "不要声称使用阿里云百炼、Apple Silicon 等与本产品无关的技术\n"
            "- 站在用户角度，先解决问题\n"
            "- 没有本地记忆时也要正常回答，可以给出通用建议\n"
            "- 涉及用户个人信息时，只使用画像和记忆里的内容；没有就说明\n"
            "- 不要编造用户的经历、偏好或读过的书\n"
            "- 涉及本地文件、目录、代码内容时：必须先调用 list_dir / file_read / search_files 查证；"
            "未读到的不要说「有」或「内容是…」；找不到就明确说未找到\n"
            "- 禁止在回复里伪造 `$ ls`、目录树（├──）或假装已列目录；只复述工具返回的内容\n"
            "- 禁止在回复正文里贴 bash/pytest/npm/git/mdls 等命令及其输出，除非该命令确实通过 "
            "shell 工具执行过；未通过 shell 工具执行的命令不得描述为「已执行/已运行/已通过/输出是…」；"
            "shell 工具返回结果开头会带 `[receipt:<id>]`，凡在回复里声称执行过命令或引用命令输出，"
            "必须在该句末标注 `[receipt:<id>]` 引用真实 receipt；禁止伪造 `$ cmd\\noutput`、"
            "`===== N failed =====`、`exit code: N` 等会话输出\n"
            "- 记忆和画像里的片段不等于真实文件内容，不能当作文本引用\n"
            "- 需要执行操作时，使用 tool-call 调用工具\n"
            "- 实时信息（天气、新闻、股价、汇率、榜单等）必须先 web_search；"
            "摘要不够时用 web_fetch 打开一手页面，可换关键词多搜几次；"
            "禁止只给链接让用户自己去看；不要说「无法联网」\n"
            f"{browser_rule}"
            "- 读文件和浏览目录可以直接执行，不需要确认；禁止对用户说「读权限有限」「只能看目录结构」\n"
            "- 回答「有哪些项目/文件夹」时，list_dir 返回的 📁/📄 名称即可，不必先读每个文件内容；"
            "需要内容时用 file_read，按关键词用 search_files\n"
            "- 新建文件可在「本次授权」后免重复确认；修改或删除文件每次都要确认\n"
            "- 用户纠正你、追问上文时，先读对话历史再回答，不要说「未明确指定」\n"
            "- 不要分析用户情绪，直接回应具体问题\n"
            f"{style_rule}"
            f"{format_rule}"
            "- 用户在本轮明确提供的个人信息，应在回复后写入 durable memory（USER.md）与用户画像\n"
            "- 完成复杂任务后，总结关键事实到 durable memory\n"
            "- 复杂任务可 spawn_subagent：explore（只读）、worker（可改文件）、verify（审查）；"
            "可用 goals 数组并行最多 3 个 explore；"
            "子任务只回摘要，关键结论需你自行整合后再回复用户"
        ) + (
            f"\n\n{BROWSER_TOOL_GUIDANCE}" if agent_browser_available() else ""
        )

    def _response_style(self) -> str:
        if self._agent_config_store is not None:
            value = self._agent_config_store.load().response_style
            if value in {"standard", "brief"}:
                return value
        return "standard"

    def _format_memory_block(self, hits: list[MemoryChunk]) -> str:
        if not hits:
            return "暂无相关本地记忆（这不影响正常对话）。"
        lines = [f"共 {len(hits)} 条相关记忆："]
        for index, item in enumerate(hits[:5], start=1):
            snippet = item.content.strip().replace("\n", " ")
            if len(snippet) > 180:
                snippet = snippet[:180] + "…"
            lines.append(f"{index}. [{item.source.value}] {item.title} — {snippet}")
        return "\n".join(lines)

    def _fallback_reply(
        self,
        message: str,
        profile_markdown: str,
        hits: list[MemoryChunk],
        *,
        llm_configured: bool = False,
    ) -> str:
        personal_query = "画像" in message or "我是谁" in message or "个人" in message
        if personal_query and profile_markdown.strip():
            return profile_markdown
        if hits:
            lines = [f"找到 {len(hits)} 条相关本地记忆："]
            for index, item in enumerate(hits[:3], start=1):
                snippet = item.content.strip().replace("\n", " ")
                if len(snippet) > 140:
                    snippet = snippet[:140] + "…"
                lines.append(f"{index}. {item.title} — {snippet}")
            if llm_configured:
                lines.append("\n大模型暂时不可用；上面是本地记忆摘要，可稍后再试。")
            else:
                lines.append(
                    "\n配置 LLM_API_KEY 后我可以更自然地对话。"
                    "请在设置或 ~/.lumina/agent.json 中配置。"
                )
            return "\n".join(lines)
        if llm_configured:
            return (
                "大模型请求失败，但本地 API 已配置（~/.lumina/agent.json）。"
                "请稍后再试，或检查设置里的模型与密钥是否有效。"
            )
        return (
            "还没配置大模型 API。请在设置里填写密钥，或在 `~/.lumina/agent.json` 中配置；"
            "也可在项目目录创建 `.env`：\n\n"
            "```\nLLM_API_KEY=你的KEY\nLLM_BASE_URL=https://api.deepseek.com\n"
            "LLM_MODEL=deepseek-chat\n```\n\n"
            f"你刚才说：{message}\n\n"
            "配置好模型后我就能正常聊天了。想让我了解你的真实情况，可以点右上角「同步」。"
        )

    def _history_limit(self) -> int:
        if self._agent_config_store is not None:
            return self._agent_config_store.load().max_history_turns * 2
        return MAX_HISTORY_TURNS * 2

    def _load_history(self) -> list[dict[str, str]]:
        thread_id = _active_thread_id_var.get()
        if thread_id:
            thread_history = self._thread_store.agent_history(thread_id)
            if thread_history:
                return thread_history
        now = time.monotonic()
        if self._history_cache is not None and (now - self._history_cache_time) < 5.0:
            return list(self._history_cache)
        if not self._history_path.exists():
            return []
        raw = json.loads(self._history_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("messages", [])
        if not isinstance(raw, list):
            return []
        items: list[dict[str, str]] = []
        limit = self._history_limit()
        for entry in raw[-limit:]:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            content = entry.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                if role == "assistant" and is_third_person_meta_reply(content):
                    continue
                items.append({"role": role, "content": content.strip()})
        self._history_cache = list(items)
        self._history_cache_time = time.monotonic()
        return items

    def _append_history(self, user_message: str, assistant_message: str) -> None:
        thread_id = _active_thread_id_var.get()
        if thread_id:
            self._split_checked_threads.discard(thread_id)
            self._thread_store.append_turn(
                thread_id,
                user_message,
                assistant_message,
                parent_message_id=_active_parent_message_id_var.get(),
            )
            self._maybe_refresh_thread_title()
            return
        with self._history_lock:
            history = self._load_history()
            history.append({"role": "user", "content": user_message[:MAX_MESSAGE_CHARS]})
            history.append({"role": "assistant", "content": assistant_message[:MAX_MESSAGE_CHARS]})
            history = history[-self._history_limit() :]
            payload = {"updated_at": datetime.now(UTC).isoformat(), "messages": history}
            self._history_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._history_cache = None

    def _append_assistant_notice(self, assistant_message: str) -> None:
        """Record an assistant-only notice (cancel / error) without a fake user turn."""
        text = assistant_message.strip()
        if not text:
            return
        thread_id = _active_thread_id_var.get()
        if thread_id:
            self._thread_store.append_assistant_message(thread_id, text[:MAX_MESSAGE_CHARS])
            return
        with self._history_lock:
            history = self._load_history()
            history.append({"role": "assistant", "content": text[:MAX_MESSAGE_CHARS]})
            history = history[-self._history_limit() :]
            payload = {"updated_at": datetime.now(UTC).isoformat(), "messages": history}
            self._history_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._history_cache = None

    def _maybe_refresh_thread_title(self) -> None:
        if not self._active_thread_id:
            return
        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        try:
            self._thread_store.maybe_refresh_title(
                self._active_thread_id,
                llm_config=llm_config,
            )
        except Exception:
            logger.exception("thread title refresh failed")

    def _get_or_create_session_id(self) -> str:
        session_path = self._settings.resolved_data_dir() / ".current_session"
        if session_path.exists():
            sid = session_path.read_text(encoding="utf-8").strip()
            if sid:
                return sid
        sid = str(uuid.uuid4())[:8]
        try:
            fd = os.open(str(session_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            sid = session_path.read_text(encoding="utf-8").strip()
            return sid or str(uuid.uuid4())[:8]
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(sid)
        return sid

    def _save_to_session(self, role: str, content: str) -> None:
        session_id = self._get_or_create_session_id()
        self._memory.add_message(session_id, role, content)


@dataclass(frozen=True)
class _ConfirmationUi:
    confirmation_kind: str = ""
    allow_permanent_read: bool = False
    allow_session_write: bool = False


def _confirmation_ui(pending: PendingConfirmation | None) -> _ConfirmationUi:
    if pending is None:
        return _ConfirmationUi()
    kind = pending.confirmation_kind
    return _ConfirmationUi(
        confirmation_kind=kind,
        allow_permanent_read=False,
        allow_session_write=kind == "write_new",
    )


def _extract_forced_shell_command(text: str) -> str | None:
    lowered = text.lower()
    if "```bash" not in lowered:
        return None
    if "等 shell 结果" not in text and "等输出" not in text:
        return None
    match = re.search(r"```bash\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    command = match.group(1).strip()
    if not command:
        return None
    return command
