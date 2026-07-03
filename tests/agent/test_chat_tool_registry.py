"""Tests for ChatToolRegistry tool assembly."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from secretary.agent.chat_tool_registry import ChatToolRegistry
from secretary.agent.llm_config import LlmConfig
from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.memory.lumina_memory import LuminaMemory
from secretary.services.cli_agent_config import CliAgentConfigStore
from secretary.services.file_auth import FileAuthService


def _registry(tmp_path: Path) -> ChatToolRegistry:
    settings = Settings(LUMINA_DATA_DIR=str(tmp_path))
    store = MemoryStore(tmp_path / "memory.db")
    memory = LuminaMemory(tmp_path)
    skills = MagicMock()
    skills.prompt_block.return_value = ""
    return ChatToolRegistry(
        settings=settings,
        store=store,
        memory=memory,
        skills=skills,
        file_auth=FileAuthService(tmp_path / "file_auth.json"),
        mcp_manager=None,
        shibei_service=None,
        sync_service=None,
        cli_agent_config_store=CliAgentConfigStore(tmp_path / "cli-agents.json"),
        get_session_id=lambda: "sess1",
        shell_working_dir=lambda: tmp_path,
        temperature=lambda: 0.7,
    )


def test_build_tools_includes_core_names(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    names = {tool.name for tool in registry.build_tools()}
    assert "file_read" in names
    assert "glob_files" in names
    assert "ask_user" in names
    assert "search_memory" in names
    assert "web_search" in names


def test_cli_spawn_disabled_by_default(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    llm = LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="test",
    )
    assert registry.make_cli_spawn_tool() is None
    tools, _ = registry.resolve_tools(
        profile=__import__("secretary.agent.agent_profile", fromlist=["AgentProfile"]).AgentProfile.BUILD,
        user_message="hello",
        suggested=(),
        filesystem_turn=False,
        light_mode=False,
        llm_config=llm,
    )
    assert all(tool.name != "spawn_cli_agent" for tool in tools)
