"""Tool assembly for parent AgentLoop sessions (extracted from ChatService)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from secretary.agent.agent_profile import AgentProfile, resolve_parent_tools
from secretary.agent.cli_agent import CliAgentRunner, SpawnCliAgentTool
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
from secretary.services.cli_agent_config import CliAgentConfigStore
from secretary.services.file_auth import FileAuthService
from secretary.services.shibei_service import ShibeiService, shibei_ready_for_memory_read
from secretary.services.todo_store import TodoStore

if True:
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
        cli_agent_config_store: CliAgentConfigStore,
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
        self._cli_agent_config_store = cli_agent_config_store
        self._get_session_id = get_session_id
        self._shell_working_dir = shell_working_dir
        self._temperature = temperature

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
        cli_spawn_tool = self.make_cli_spawn_tool()

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
                cli_spawn_tool=cli_spawn_tool,
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
                cli_spawn_tool=None,
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
                cli_spawn_tool=None,
            )
        return guard_tools_for_profile(profile, tools), spawn_tool

    def build_tools(self) -> list[Tool]:
        from secretary.agent.p0_tools import (
            AskUserTool,
            ClarifyTool,
            GlobFilesTool,
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

        tools: list[Tool] = [
            ListDirTool(),
            FileReadTool(),
            ReadDocumentTool(),
            SearchFilesTool(),
            GlobFilesTool(),
            SearchMemoryTool(self._store),
            WebSearchTool(),
            WebFetchTool(),
            MemoryTool(self._memory),
            SessionSearchTool(self._memory),
            FileWriteTool(),
            PatchTool(),
            FileDeleteTool(),
            ShellTool(),
            CodeExecTool(),
            TodoTool(TodoStore(todo_path)),
            SkillsListTool(self._skills),
            SkillViewTool(self._skills),
            ClarifyTool(),
            AskUserTool(),
        ]
        if self._sync_service is not None:
            from secretary.agent.tools.connector_tools import (
                ConnectorStatusTool,
                ListConnectorsTool,
                SyncSourceTool,
            )

            tools.extend(
                [
                    ListConnectorsTool(self._sync_service),
                    ConnectorStatusTool(self._sync_service),
                    SyncSourceTool(self._sync_service),
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

    def make_cli_spawn_tool(self) -> SpawnCliAgentTool | None:
        if not self._cli_agent_config_store.is_enabled():
            return None
        projects_dir: Path | None = None
        raw = self._settings.projects_dir.strip()
        if raw:
            expanded = Path(raw).expanduser()
            if expanded.is_dir():
                projects_dir = expanded
        runner = CliAgentRunner(
            self._cli_agent_config_store,
            projects_dir=projects_dir,
            audit_dir=self._settings.resolved_data_dir() / "logs" / "cli-agent",
        )
        return SpawnCliAgentTool(runner, default_cwd=self._shell_working_dir())

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
