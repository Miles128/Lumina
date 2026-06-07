"""Hermes-style chat orchestration with Agent Loop."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from secretary.agent.executable_skill import ExecutableSkillManager
from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig, resolve_llm_config
from secretary.agent.loop import LoopResult, PendingConfirmation
from secretary.agent.tools.base import Tool
from secretary.agent.tools.fs import FileDeleteTool, FileReadTool, FileWriteTool, ListDirTool
from secretary.agent.tools.memory_tools import MemoryTool, SearchMemoryTool, SessionSearchTool
from secretary.agent.tools.shell import ShellTool
from secretary.agent.tools.web import WebFetchTool
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.web_routing import WebSearchPlan, resolve_web_search
from secretary.agent.identity import (
    LUMINA_DEFAULT_STYLE,
    LUMINA_IDENTITY_SYSTEM_BLOCK,
    get_author_reply,
    get_identity_reply,
    is_author_request,
    is_identity_request,
)
from secretary.agent.prompt_gate import GateAction, GateDecision, PromptGate
from secretary.agent.reply_rewriter import rewrite_if_forbidden_label
from secretary.agent.reply_safety import is_third_person_meta_reply, sanitize_user_facing_reply
from secretary.agent.skills import SkillManager
from secretary.agent.soul import load_soul
from secretary.agent.subagent import SpawnContext, SpawnSubagentTool, SubAgentDeps, SubAgentRunner
from secretary.agent.turn_orchestrator import AgentTurnPlan, TurnOrchestrator
from secretary.config import Settings
from secretary.core.types import MemoryChunk
from secretary.exceptions import AgentError
from secretary.memory.db import MemoryStore
from secretary.memory.hermes_memory import HermesMemory
from secretary.services.agent_config import AgentConfigStore
from secretary.services.background_review import BackgroundReviewService
from secretary.services.file_auth import FileAuthService
from secretary.services.profile_service import ProfileService
from secretary.services.todo_store import TodoStore

if TYPE_CHECKING:
    from secretary.agent.mcp_manager import McpManager
    from secretary.services.sync import SyncService

MAX_HISTORY_TURNS = 16
MAX_MESSAGE_CHARS = 2000


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
        self._hermes = HermesMemory(settings.resolved_data_dir())
        self._background_review = BackgroundReviewService(
            self._hermes,
            profile_service=self._profile_service,
        )
        self._exec_skills = ExecutableSkillManager(settings.resolved_data_dir())
        self._pending: PendingConfirmation | None = None
        self._pending_messages: list[dict[str, str]] | None = None
        self._pending_llm_config: LlmConfig | None = None
        self._prompt_gate = PromptGate(settings, agent_config_store)
        self._turn_orchestrator = TurnOrchestrator(self._file_auth)
        self._mcp_manager = mcp_manager

    @property
    def hermes_memory(self) -> HermesMemory:
        return self._hermes

    @property
    def exec_skills(self) -> ExecutableSkillManager:
        return self._exec_skills

    @property
    def pending_confirmation(self) -> PendingConfirmation | None:
        return self._pending

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

    def reply(
        self,
        message: str,
        *,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        location_city: str | None = None,
        location_lat: float | None = None,
        location_lng: float | None = None,
    ) -> ChatResult:
        cleaned = message.strip()
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

        web_plan = resolve_web_search(
            cleaned,
            history,
            location_city=location_city,
            location_lat=location_lat,
            location_lng=location_lng,
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
        )

    def confirm_action(
        self,
        approved: bool,
        *,
        grant_permanent_read: bool = False,
        grant_session_write: bool = False,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> ChatResult:
        pending = self._pending
        messages = self._pending_messages
        llm_config = self._pending_llm_config
        self._pending = None
        self._pending_messages = None
        self._pending_llm_config = None

        if not approved or pending is None or messages is None or llm_config is None:
            reply = "好的，已取消操作。"
            self._append_history("system", reply)
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

        tools = self._build_tools()
        result = self._turn_orchestrator.run_confirmed_action(
            llm_config,
            tools,
            pending,
            messages,
            temperature=0.7,
            working_dir=self._shell_working_dir(),
            progress_callback=progress_callback,
        )

        if result.pending_confirmation:
            self._pending = result.pending_confirmation
            self._pending_messages = messages + [
                {"role": "assistant", "content": result.reply},
            ]
            self._pending_llm_config = llm_config

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
    ) -> ChatResult:
        tools = list(used_tools or [])
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
        system_prompt = self._build_system_prompt(profile_markdown, hits)
        session_id = self._get_or_create_session_id()
        self._hermes.create_session(session_id)
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
            reply, verified, note = self._prepare_user_reply(reply, cleaned, llm_config)
            self._hermes.end_session(session_id, summary=reply[:200])
            self._append_history(cleaned, reply)
            self._save_to_session("assistant", reply)
            self._background_review.schedule(cleaned, reply, llm_config)
            return ChatResult(
                reply=reply,
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
                f"{self._fallback_reply(cleaned, profile_markdown, hits)}"
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
    ) -> ChatResult:
        """Realtime/web queries: agent loop with web_search + web_fetch (model picks tools)."""
        from secretary.agent.web_research import WEB_RESEARCH_APPENDIX

        session_id = self._get_or_create_session_id()
        self._hermes.create_session(session_id)
        self._save_to_session("user", cleaned)

        from secretary.agent.browser_tools import agent_browser_available
        from secretary.agent.web_research import BROWSER_TOOL_GUIDANCE

        appendix = WEB_RESEARCH_APPENDIX
        if agent_browser_available():
            appendix += "\n\n" + BROWSER_TOOL_GUIDANCE
        if plan.search_query.strip() != cleaned.strip():
            appendix += f"\n- 若首轮检索不佳，可尝试关键词：{plan.search_query}"

        system_prompt = self._build_system_prompt(profile_markdown, hits) + "\n\n" + appendix
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(self._load_history())
        messages.append({"role": "user", "content": cleaned})

        tools = self._pick_web_tools(cleaned)
        agent_plan = AgentTurnPlan(messages=messages, max_steps=8, tools=tools)

        if progress_callback is not None:
            progress_callback(
                ProgressEvent(
                    kind="iteration_started",
                    iteration=1,
                    message="网络连接 · 开始联网检索",
                )
            )

        try:
            result = self._turn_orchestrator.run_agent_turn(
                llm_config,
                agent_plan,
                temperature=self._temperature(),
                working_dir=self._shell_working_dir(),
                progress_callback=progress_callback,
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
    ) -> ChatResult:
        system_prompt = self._build_system_prompt(profile_markdown, hits)
        session_id = self._get_or_create_session_id()
        self._hermes.create_session(session_id)
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
            self._pending = pending
            self._pending_messages = messages
            self._pending_llm_config = llm_config
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
        from secretary.agent.grounding import is_filesystem_question

        filesystem_turn = is_filesystem_question(cleaned)
        max_steps = 4 if filesystem_turn else (3 if light_mode else 8)
        suggested = decision.intent.suggested_tools if decision.intent else ()
        if filesystem_turn:
            tools = self._build_tools()
        elif light_mode:
            tools = self._pick_tools(suggested)
        else:
            tools = self._append_browser_tools(self._build_tools(), cleaned)

        if filesystem_turn or not light_mode:
            tools = [*tools, self._make_spawn_tool(llm_config, session_id)]

        plan = AgentTurnPlan(messages=messages, max_steps=max_steps, tools=tools)

        try:
            result = self._turn_orchestrator.run_agent_turn(
                llm_config,
                plan,
                temperature=self._temperature(),
                working_dir=self._shell_working_dir(),
                progress_callback=progress_callback,
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
                f"{self._fallback_reply(cleaned, profile_markdown, hits)}"
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
        safe_reply, grounding_verified, grounding_note = self._prepare_user_reply(
            result.reply,
            cleaned,
            llm_config,
            used_tools=result.used_tools,
            grounding_verified=result.grounding_verified,
            grounding_note=result.grounding_note,
        )

        if result.pending_confirmation:
            self._pending = result.pending_confirmation
            self._pending_messages = messages + [
                {"role": "assistant", "content": safe_reply},
            ]
            self._pending_llm_config = llm_config

        self._hermes.end_session(session_id, summary=safe_reply[:200])

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
            self._hermes.save_episode(
                episode_id=episode_id,
                task=cleaned[:500],
                steps=steps_data,
                result=safe_reply[:2000],
                success=True,
                tools_used=result.used_tools,
            )

        self._append_history(cleaned, safe_reply)
        self._save_to_session("assistant", safe_reply)

        if result.pending_confirmation is None:
            self._background_review.schedule(cleaned, safe_reply, llm_config)

        cui3 = _confirmation_ui(result.pending_confirmation)
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
        )

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

        rewritten = rewrite_if_forbidden_label(raw_reply, user_message, llm_config)
        sanitized = sanitize_user_facing_reply(rewritten, user_message)
        return enforce_grounded_reply(
            sanitized,
            user_message,
            list(used_tools or []),
            grounding_verified=grounding_verified,
            grounding_note=grounding_note,
        )

    def _temperature(self) -> float:
        if self._agent_config_store is not None:
            return self._agent_config_store.load().temperature
        return 0.7

    def _shell_working_dir(self) -> Path:
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

        tools: list[Tool] = [WebSearchTool(), WebFetchTool()]
        tools.extend(self._browser_tool_instances(user_message))
        return tools

    def _append_browser_tools(self, tools: list[Tool], user_message: str) -> list[Tool]:
        from secretary.agent.browser_routing import needs_browser_tools

        if not needs_browser_tools(user_message):
            return tools
        existing = {tool.name for tool in tools}
        merged = list(tools)
        for tool in self._browser_tool_instances(user_message):
            if tool.name not in existing:
                merged.append(tool)
                existing.add(tool.name)
        return merged

    def _browser_tool_instances(self, user_message: str) -> list[Tool]:
        from secretary.agent.browser_routing import needs_browser_tools
        from secretary.agent.browser_tools import build_browser_tools

        if not needs_browser_tools(user_message):
            return []
        return build_browser_tools(self._get_or_create_session_id())

    def _pick_tools(self, suggested: tuple[str, ...]) -> list[Tool]:
        all_tools = {tool.name: tool for tool in self._build_tools()}
        if suggested:
            picked = [all_tools[name] for name in suggested if name in all_tools]
            if picked:
                return picked
        defaults = ("search_memory", "session_search", "web_search")
        return [all_tools[name] for name in defaults if name in all_tools]

    def _build_tools(self) -> list[Tool]:
        from secretary.agent.p0_tools import (
            ClarifyTool,
            PatchTool,
            SearchFilesTool,
            SkillsListTool,
            SkillViewTool,
            TodoTool,
        )
        from secretary.agent.web_search import WebSearchTool

        session_id = self._get_or_create_session_id()
        todo_path = self._settings.resolved_data_dir() / "todos" / f"{session_id}.json"

        tools: list[Tool] = [
            ListDirTool(),
            FileReadTool(),
            SearchFilesTool(),
            SearchMemoryTool(self._store),
            WebSearchTool(),
            WebFetchTool(),
            MemoryTool(self._hermes),
            SessionSearchTool(self._hermes),
            FileWriteTool(),
            PatchTool(),
            FileDeleteTool(),
            ShellTool(),
            TodoTool(TodoStore(todo_path)),
            SkillsListTool(self._skills),
            SkillViewTool(self._skills),
            ClarifyTool(),
        ]
        if self._mcp_manager is not None:
            tools.extend(self._mcp_manager.get_tools())
        return tools

    def _make_spawn_tool(self, llm_config: LlmConfig, session_id: str) -> SpawnSubagentTool:
        spawn_context = SpawnContext(parent_session_id=session_id, depth=0)
        deps = SubAgentDeps(
            llm_config=llm_config,
            file_auth=self._file_auth,
            memory_store=self._store,
            hermes=self._hermes,
            lumina_dir=self._settings.resolved_data_dir(),
            temperature=min(self._temperature(), 0.5),
        )
        runner = SubAgentRunner(deps)
        return SpawnSubagentTool(runner, spawn_context)

    def _build_system_prompt(self, profile_markdown: str, hits: list[MemoryChunk]) -> str:
        from secretary.agent.browser_tools import agent_browser_available
        from secretary.agent.web_research import BROWSER_TOOL_GUIDANCE

        soul = load_soul(self._settings.resolved_data_dir())
        skills = self._skills.prompt_block()
        exec_skills = self._exec_skills.prompt_block()
        memory_block = self._format_memory_block(hits)
        profile_block = profile_markdown.strip() or "暂无个人画像。用户尚未同步数据源。"

        hermes_snapshot = self._hermes.prompt_snapshot()
        hermes_section = ""
        if hermes_snapshot:
            hermes_section = f"\n\n## Persistent Memory\n{hermes_snapshot}"
        style_rule = (
            "- 语气档位：简短。先给结论，优先 1-3 句；只有必要时再补一句。\n"
            if self._response_style() == "brief"
            else f"- 语气档位：标准；在「{LUMINA_DEFAULT_STYLE}」基础上，先给结论，再补关键细节，避免啰嗦。\n"
        )
        browser_rule = ""
        if agent_browser_available():
            browser_rule = (
                "- 静态页优先 web_fetch；JS 渲染/登录/榜单等用 browser_open → browser_snapshot → "
                "browser_click/browser_fill；完成后 browser_close\n"
            )

        return (
            f"{soul}\n\n"
            f"{LUMINA_IDENTITY_SYSTEM_BLOCK}\n\n"
            "## 已安装技能\n"
            f"{skills}\n\n"
            "## 可执行技能\n"
            f"{exec_skills}\n\n"
            "## 关于用户的资料（用户画像与本地文档，描述用户本人，不是灵犀）\n"
            f"{profile_block[:6000]}\n\n"
            "## 关于用户的本地记忆（用户经历与资料，不是灵犀的属性）\n"
            f"{memory_block}\n"
            f"{hermes_section}\n\n"
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
            "- 用户在本轮明确提供的个人信息，应在回复后写入 durable memory（USER.md）与用户画像\n"
            "- 完成复杂任务后，总结关键事实到 durable memory\n"
            "- 复杂任务可 spawn_subagent：explore（只读）、worker（可改文件）、verify（审查）；"
            "可用 goals 数组并行最多 2 个 explore；"
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
            lines.append(
                "\n配置 LLM_API_KEY 或在 Hermes config.yaml 里配好模型后，我可以更自然地对话。"
            )
            return "\n".join(lines)
        return (
            "我可以和你对话。当前还没配置大模型 API（可在 `.env` 设置 LLM_API_KEY，"
            "或沿用 Hermes 的 ~/.hermes/config.yaml）。\n\n"
            f"你刚才说：{message}\n\n"
            "即使没有本地记忆，配置好模型后我也能正常聊天。"
            "想让我了解你的真实情况，可以点右上角「同步」。"
        )

    def _history_limit(self) -> int:
        if self._agent_config_store is not None:
            return self._agent_config_store.load().max_history_turns * 2
        return MAX_HISTORY_TURNS * 2

    def _load_history(self) -> list[dict[str, str]]:
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
        return items

    def _append_history(self, user_message: str, assistant_message: str) -> None:
        history = self._load_history()
        history.append({"role": "user", "content": user_message[:MAX_MESSAGE_CHARS]})
        history.append({"role": "assistant", "content": assistant_message[:MAX_MESSAGE_CHARS]})
        history = history[-self._history_limit() :]
        payload = {"updated_at": datetime.now(UTC).isoformat(), "messages": history}
        self._history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _get_or_create_session_id(self) -> str:
        session_path = self._settings.resolved_data_dir() / ".current_session"
        if session_path.exists():
            sid = session_path.read_text(encoding="utf-8").strip()
            if sid:
                return sid
        sid = str(uuid.uuid4())[:8]
        session_path.write_text(sid, encoding="utf-8")
        return sid

    def _save_to_session(self, role: str, content: str) -> None:
        session_id = self._get_or_create_session_id()
        self._hermes.add_message(session_id, role, content)


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
