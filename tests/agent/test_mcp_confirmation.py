"""MCP confirmation must use remote tool name / Tool flags, not server-name substrings."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.agent_profile import AgentProfile, resolve_parent_tools
from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.mcp_manager import _needs_confirmation, mcp_tool_needs_confirmation
from secretary.agent.permission_guard import tool_allowed_for_profile
from secretary.agent.tools.base import Tool
from secretary.agent.tools.fs import ListDirTool


class _FakeMcpTool(Tool):
    def __init__(self, name: str, *, needs_confirmation: bool) -> None:
        self.name = name
        self.description = name
        self.needs_confirmation = needs_confirmation
        self.read_only = not needs_confirmation

    def _parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, arguments: dict, working_dir: Path) -> str:
        return "ok"


def test_needs_confirmation_uses_prefix_not_substring() -> None:
    assert _needs_confirmation("delete_item") is True
    assert _needs_confirmation("unread_count") is True
    assert _needs_confirmation("read_file") is False
    assert _needs_confirmation("list_notes") is False
    assert _needs_confirmation("get_status") is False
    assert _needs_confirmation("search_docs") is False
    assert _needs_confirmation("fetch_url") is False


def test_mcp_full_name_defaults_to_confirm_without_bare_remote() -> None:
    # Full mcp_{server}_{tool} cannot be split reliably — prefer confirm.
    # Construction-time McpBridgeTool classifies via bare remote name instead.
    assert mcp_tool_needs_confirmation("mcp_search_hub_delete_item") is True
    assert mcp_tool_needs_confirmation("mcp_fs_read_file") is True


def test_confirmation_policy_trusts_tool_flag_for_mcp_write() -> None:
    tool = _FakeMcpTool("mcp_search_hub_delete_item", needs_confirmation=True)
    needs, kind = tool_requires_confirmation(
        tool,
        {},
        working_dir=Path("/tmp"),
        file_auth=None,
    )
    assert needs is True
    assert kind == "action"


def test_confirmation_policy_skips_mcp_read() -> None:
    tool = _FakeMcpTool("mcp_fs_read_file", needs_confirmation=False)
    needs, kind = tool_requires_confirmation(
        tool,
        {},
        working_dir=Path("/tmp"),
        file_auth=None,
    )
    assert needs is False
    assert kind == ""


def test_plan_guard_blocks_mcp_write_even_if_server_name_looks_read() -> None:
    tool = _FakeMcpTool("mcp_search_hub_delete_item", needs_confirmation=True)
    assert tool_allowed_for_profile(AgentProfile.PLAN, tool) is False


def test_plan_guard_allows_mcp_read() -> None:
    tool = _FakeMcpTool("mcp_fs_read_file", needs_confirmation=False)
    assert tool_allowed_for_profile(AgentProfile.PLAN, tool) is True


def test_ask_profile_excludes_mcp_write_tools() -> None:
    tools = [
        _FakeMcpTool("mcp_search_hub_delete_item", needs_confirmation=True),
        _FakeMcpTool("mcp_fs_read_file", needs_confirmation=False),
        ListDirTool(),
    ]
    picked = resolve_parent_tools(AgentProfile.ASK, tools)
    names = {t.name for t in picked}
    assert "mcp_fs_read_file" in names
    assert "mcp_search_hub_delete_item" not in names
