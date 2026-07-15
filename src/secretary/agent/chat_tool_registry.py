"""Tool assembly for parent AgentLoop sessions (extracted from ChatService)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from secretary.agent.agent_profile import AgentProfile, resolve_parent_tools
from secretary.agent.llm_config import LlmConfig
from secretary.agent.permission_guard import guard_tools_for_profile
from secretary.agent.subagent import SpawnContext, SpawnSubagentTool, SubAgentDeps
from secretary.agent.tools.base import Tool
from secretary.agent.tools.fs import FileDeleteTool, FileReadTool, FileWriteTool, ListDirTool
from secretary.agent.tools.memory_tools import MemoryTool, SearchMemoryTool, SessionSearchTool
from secretary.agent.tools.shell import ShellTool
from secretary.agent.tools.web import WebFetchTool
from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.memory.lumina_memory import LuminaMemory
from secretary.services.file_auth import FileAuthService
from secretary.services.shibei_service import ShibeiService, shibei_ready_for_memory_read
from secretary.services.todo_store import TodoStore

if TYPE_CHECKING:
    from secretary.agent.mcp_manager import McpManager
    from secretary.agent.skills import SkillManager
    from secretary.services.sync import SyncService


class ChatToolRegistry:
    def __init__(
        self,
        *,
        settings: Settings,
        store: MemoryStore,
        memory: LuminaMemory,
        skills: SkillManager,
        file_auth: FileAuthService,
        mcp_manager: McpManager | None,
        shibei_service: ShibeiService | None,
        sync_service: SyncService | None,
        get_session_id: Callable[[], str],
        shell_working_dir: Callable[[], Path],
        temperature: Callable[[], float],
    ) -> None:
        self._settings = settings
        self._store = store
        self._memory = memory
        self._skills = skills
        self._file_auth = file_auth
        self._mcp_manager = mcp_manager
        self._shibei_service = shibei_service
        self._sync_service = sync_service
        self._get_session_id = get_session_id
        self._shell_working_dir = shell_working_dir
        self._temperature = temperature
        self._stateless_tool_cache: dict[str, Tool] = {}

    def _get_or_create_tool(self, key: str, factory: Callable[[], Tool]) -> Tool:
        """Return a cached stateless tool instance, creating it on first use."""
        cached = self._stateless_tool_cache.get(key)
        if cached is not None:
            return cached
        tool = factory()
        self._stateless_tool_cache[key] = tool
        return tool

    def resolve_tools(
        self,
        *,
        profile: AgentProfile,
        user_message: str,
        suggested: tuple[str, ...],
        filesystem_turn: bool,
        light_mode: bool,
        llm_config: LlmConfig,
    ) -> tuple[list[Tool], object | None]:
        spawn_tool = self.make_spawn_tool(llm_config)

        if profile is AgentProfile.BUILD:
            if filesystem_turn:
                base_tools = self.build_tools()
            elif light_mode:
                base_tools = self.pick_tools(suggested)
            else:
                base_tools = self.append_browser_tools(
                    self.build_tools(),
                    user_message,
                    profile=profile,
                )
            tools = resolve_parent_tools(
                profile,
                base_tools,
                spawn_tool=spawn_tool,
            )
        elif profile is AgentProfile.ASK:
            base_tools = self.append_browser_tools(
                self.build_tools(),
                user_message,
                profile=profile,
            )
            tools = resolve_parent_tools(
                profile,
                base_tools,
                spawn_tool=None,
            )
        else:
            base_tools = self.append_browser_tools(
                self.build_tools(),
                user_message,
                profile=profile,
            )
            tools = resolve_parent_tools(
                profile,
                base_tools,
                spawn_tool=None,
            )
        return guard_tools_for_profile(profile, tools), spawn_tool

    def build_tools(self) -> list[Tool]:
        from secretary.agent.p0_tools import (
            AskUserTool,
            ClarifyTool,
            GlobFilesTool,
            NotesTool,
            PatchTool,
            SearchFilesTool,
            SkillsListTool,
            SkillViewTool,
            TodoTool,
        )
        from secretary.agent.tools.code_exec import CodeExecTool
        from secretary.agent.tools.documents import ReadDocumentTool
        from secretary.agent.web_search import WebSearchTool

        session_id = self._get_session_id()
        todo_path = self._settings.resolved_data_dir() / "todos" / f"{session_id}.json"
        notes_path = self._settings.resolved_data_dir() / "NOTES.md"

        tools: list[Tool] = [
            self._get_or_create_tool("list_dir", ListDirTool),
            self._get_or_create_tool("file_read", FileReadTool),
            self._get_or_create_tool("read_document", ReadDocumentTool),
            self._get_or_create_tool("search_files", SearchFilesTool),
            self._get_or_create_tool("glob_files", GlobFilesTool),
            self._get_or_create_tool("search_memory", lambda: SearchMemoryTool(self._store)),
            self._get_or_create_tool("web_search", WebSearchTool),
            self._get_or_create_tool("web_fetch", WebFetchTool),
            self._get_or_create_tool("memory", lambda: MemoryTool(self._memory)),
            self._get_or_create_tool("session_search", lambda: SessionSearchTool(self._memory)),
            self._get_or_create_tool("file_write", FileWriteTool),
            self._get_or_create_tool("patch", PatchTool),
            self._get_or_create_tool("file_delete", FileDeleteTool),
            self._get_or_create_tool("shell", ShellTool),
            self._get_or_create_tool("code_exec", CodeExecTool),
            TodoTool(TodoStore(todo_path)),
            self._get_or_create_tool("notes", lambda: NotesTool(notes_path)),
            self._get_or_create_tool("skills_list", lambda: SkillsListTool(self._skills)),
            self._get_or_create_tool("skill_view", lambda: SkillViewTool(self._skills)),
            self._get_or_create_tool("clarify", ClarifyTool),
            self._get_or_create_tool("ask_user", AskUserTool),
        ]
        from secretary.agent.structured_cards import EmitCardTool

        tools.append(self._get_or_create_tool("emit_card", EmitCardTool))
        if self._sync_service is not None:
            from secretary.agent.tools.connector_tools import (
                ConnectorStatusTool,
                ListConnectorsTool,
                SyncSourceTool,
            )

            builtin_registry = (
                self._mcp_manager._builtin
                if self._mcp_manager is not None
                else None
            )
            tools.extend(
                [
                    ListConnectorsTool(
                        registry=builtin_registry,
                        sync_service=self._sync_service,
                    ),
                    ConnectorStatusTool(
                        registry=builtin_registry,
                        sync_service=self._sync_service,
                    ),
                    SyncSourceTool(
                        self._sync_service,
                        mcp_manager=self._mcp_manager,
                    ),
                ]
            )
        if self._mcp_manager is not None:
            tools.extend(self._mcp_manager.get_tools())
        if self._shibei_service is not None and self._shibei_service.is_enabled():
            from secretary.agent.tools.shibei_tools import (
                ShibeiImportTool,
                ShibeiListSourcesTool,
                ShibeiSearchTool,
            )

            tools.extend(
                [
                    ShibeiSearchTool(self._shibei_service),
                    ShibeiImportTool(self._shibei_service),
                    ShibeiListSourcesTool(self._shibei_service),
                ]
            )
        return tools

    def pick_tools(self, suggested: tuple[str, ...]) -> list[Tool]:
        all_tools = {tool.name: tool for tool in self.build_tools()}
        shibei_first = shibei_ready_for_memory_read(self._shibei_service)
        if suggested:
            names = list(suggested)
            if shibei_first and "shibei_search" not in names:
                if any(name in names for name in ("search_memory", "session_search")):
                    names.insert(0, "shibei_search")
            picked = [all_tools[name] for name in names if name in all_tools]
            if picked:
                return picked
        defaults = self._default_memory_tool_names()
        return [all_tools[name] for name in defaults if name in all_tools]

    def make_spawn_tool(
        self,
        llm_config: LlmConfig,
        *,
        parent_session_id: str | None = None,
    ) -> SpawnSubagentTool:
        session_id = (parent_session_id or "").strip() or self._get_session_id()
        spawn_context = SpawnContext(parent_session_id=session_id, depth=0)
        deps = SubAgentDeps(
            llm_config=llm_config,
            file_auth=self._file_auth,
            memory_store=self._store,
            memory=self._memory,
            lumina_dir=self._settings.resolved_data_dir(),
            temperature=min(self._temperature(), 0.5),
        )
        return SpawnSubagentTool(deps, spawn_context)

    def append_browser_tools(
        self,
        tools: list[Tool],
        user_message: str,
        *,
        profile: AgentProfile = AgentProfile.BUILD,
    ) -> list[Tool]:
        from secretary.agent.browser_routing import needs_browser_tools

        if not needs_browser_tools(user_message, profile=profile):
            return tools
        existing = {tool.name for tool in tools}
        merged = list(tools)
        for tool in self._browser_tool_instances(user_message, profile=profile):
            if tool.name not in existing:
                merged.append(tool)
                existing.add(tool.name)
        return merged

    def _browser_tool_instances(
        self,
        user_message: str,
        *,
        profile: AgentProfile = AgentProfile.BUILD,
    ) -> list[Tool]:
        from secretary.agent.browser_routing import needs_browser_tools
        from secretary.agent.browser_tools import build_browser_tools

        if not needs_browser_tools(user_message, profile=profile):
            return []
        return build_browser_tools(self._get_session_id())

    def _default_memory_tool_names(self) -> tuple[str, ...]:
        if shibei_ready_for_memory_read(self._shibei_service):
            return ("shibei_search", "session_search", "search_memory", "web_search")
        return ("search_memory", "session_search", "web_search")
