"""FR-46: read-only harness policy summary for settings UI."""

from __future__ import annotations

from typing import Any

from secretary.agent.agent_profile import PROFILE_LABELS, AgentProfile
from secretary.agent.subagent.policy import (
    MAX_PARALLEL_EXPLORE,
    MAX_SPAWN_DEPTH,
    MAX_SPAWNS_PER_TURN,
)
from secretary.agent.subagent.registry import get_archetype, list_archetype_names
from secretary.services.file_auth import FileAuthService


def _archetype_tools(name: str) -> list[str]:
    spec = get_archetype(name)
    if spec is None:
        return []
    if spec.tool_names is None:
        # explore / verify defaults: read-oriented (see registry.resolve_tools)
        return ["ls", "read", "grep", "search_memory", "web_search"]
    return sorted(spec.tool_names)


def build_policy_view(file_auth: FileAuthService | None = None) -> dict[str, Any]:
    archetypes = []
    for name in list_archetype_names():
        if name == "reflect":
            continue  # internal; not user-spawned from chat palette narrative
        spec = get_archetype(name)
        tools = _archetype_tools(name)
        can_write = bool(
            {
                "file_write",
                "write",
                "patch",
                "edit",
                "move",
                "file_delete",
                "shell",
                "code_exec",
            }
            & set(tools)
        )
        archetypes.append(
            {
                "name": name,
                "tools": tools,
                "can_write": can_write,
                "can_spawn": False,
                "max_steps": spec.max_steps if spec else 0,
            }
        )

    profiles = [
        {
            "id": profile.value,
            "label": PROFILE_LABELS[profile],
            "can_spawn": profile == AgentProfile.BUILD,
            "can_write": profile == AgentProfile.BUILD,
        }
        for profile in (
            AgentProfile.AUTO,
            AgentProfile.BUILD,
            AgentProfile.ASK,
            AgentProfile.PLAN,
        )
    ]

    grants = {
        "permanent_read": bool(file_auth and file_auth.has_permanent_read()),
        "session_write_new": bool(file_auth and file_auth.has_session_write_new()),
        "session_code_exec": bool(file_auth and file_auth.has_session_code_exec()),
    }

    return {
        "max_spawn_depth": MAX_SPAWN_DEPTH,
        "max_spawns_per_turn": MAX_SPAWNS_PER_TURN,
        "max_parallel_explore": MAX_PARALLEL_EXPLORE,
        "profiles": profiles,
        "archetypes": archetypes,
        "confirm_kinds": [
            {"id": "write_new", "label": "新建文件写入"},
            {"id": "write_modify", "label": "修改已有文件"},
            {"id": "write_delete", "label": "删除文件"},
            {"id": "shell", "label": "非只读 Shell"},
            {"id": "action", "label": "其他写操作 / code_exec / MCP"},
        ],
        "session_grants": grants,
        "notes": [
            "子 Agent 不可再 spawn（depth=1）。",
            "多路 explore 由主 Agent 汇总；不做多 Agent 辩论。",
            "危险操作在确认面板中批准；会话级授权本回合有效。",
        ],
    }
