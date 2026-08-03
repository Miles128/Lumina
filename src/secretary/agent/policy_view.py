"""FR-46: harness delegation + confirmation policy for settings UI."""

from __future__ import annotations

from typing import Any, cast

from secretary.agent.agent_profile import PROFILE_LABELS, AgentProfile
from secretary.agent.harness_config import (
    ConfirmRequireConfig,
    HarnessConfig,
    PermissionMode,
    apply_permission_mode,
    infer_permission_mode,
)
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


def build_policy_view(
    file_auth: FileAuthService | None = None,
    *,
    harness: HarnessConfig | None = None,
) -> dict[str, Any]:
    harness = harness or HarnessConfig()
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

    mode = harness.permission_mode
    require = harness.require_confirm
    inferred = infer_permission_mode(require)
    if mode != "custom" and inferred != mode and inferred != "custom":
        # Prefer inferred when table matches a preset (keeps UI honest after edits).
        mode = inferred
    elif mode != "custom" and inferred == "custom":
        mode = "custom"

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
        "permission_mode": mode,
        "require_confirm": require.model_dump(),
        "session_grants": grants,
        "notes": [
            "子 Agent 不可再 spawn（depth=1）。",
            "多路 explore 由主 Agent 汇总；不做多 Agent 辩论。",
            "危险操作在确认面板中批准；会话级授权本进程有效。",
            "权限档位：normal（全确认）· auto（新建/code_exec 免）· yolo（几乎不确认）。",
        ],
        "editable": True,
    }


def apply_session_grants_for_mode(
    file_auth: FileAuthService,
    mode: str,
) -> None:
    """Apply default session-grant side effects when a named mode is selected."""
    if mode == "normal":
        file_auth.clear_session_write_new()
        file_auth.clear_session_code_exec()
        return
    if mode == "auto":
        file_auth.grant_session_write_new()
        file_auth.grant_session_code_exec()
        return
    if mode == "yolo":
        file_auth.grant_session_write_new()
        file_auth.grant_session_code_exec()
        file_auth.grant_permanent_read()


def resolve_policy_update(
    *,
    current: HarnessConfig,
    permission_mode: str | None,
    require_confirm: ConfirmRequireConfig | None,
    session_grants: dict[str, bool] | None,
    file_auth: FileAuthService | None,
) -> tuple[HarnessConfig, str]:
    """Merge policy update into harness; optionally apply session grants.

    Returns (updated_harness, effective_mode).
    """
    mode: PermissionMode = cast(
        PermissionMode,
        permission_mode or current.permission_mode,
    )
    if require_confirm is None and mode in {"normal", "auto", "yolo"}:
        require = apply_permission_mode(mode)
    elif require_confirm is not None:
        require = require_confirm
        # Fine-grained table is source of truth; re-infer mode for persistence.
        mode = infer_permission_mode(require)
    else:
        require = current.require_confirm
        mode = infer_permission_mode(require)

    updated = current.model_copy(
        update={
            "permission_mode": mode,
            "require_confirm": require,
        }
    )

    if file_auth is not None:
        if permission_mode in {"normal", "auto", "yolo"} and session_grants is None:
            apply_session_grants_for_mode(file_auth, permission_mode)
        if session_grants is not None:
            if "permanent_read" in session_grants:
                if session_grants["permanent_read"]:
                    file_auth.grant_permanent_read()
                else:
                    file_auth.revoke_permanent_read()
            if "session_write_new" in session_grants:
                if session_grants["session_write_new"]:
                    file_auth.grant_session_write_new()
                else:
                    file_auth.clear_session_write_new()
            if "session_code_exec" in session_grants:
                if session_grants["session_code_exec"]:
                    file_auth.grant_session_code_exec()
                else:
                    file_auth.clear_session_code_exec()

    return updated, mode
