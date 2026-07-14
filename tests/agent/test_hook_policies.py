"""Unit tests for hook policies."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.agent_profile import AgentProfile
from secretary.agent.hook_policies import (
    CommandDenyHook,
    PathAllowlistHook,
    PlanPermissionHook,
    TruncateToolOutputHook,
    build_default_hooks,
)
from secretary.agent.lifecycle_hooks import AfterToolContext, ToolExecContext
from secretary.agent.stop_hooks import LoopSnapshot


def _snap() -> LoopSnapshot:
    return LoopSnapshot(iteration=0, max_iterations=3, latest_user_message="")


def test_command_deny_blocks_sudo() -> None:
    hook = CommandDenyHook()
    decision = hook.before_tool_execution(
        ToolExecContext(
            snapshot=_snap(),
            tool_name="shell",
            arguments={"command": "sudo ls"},
            working_dir=Path("."),
        )
    )
    assert decision.should_skip


def test_path_allowlist_empty_allows_all() -> None:
    hook = PathAllowlistHook(allowlist=())
    decision = hook.before_tool_execution(
        ToolExecContext(
            snapshot=_snap(),
            tool_name="file_read",
            arguments={"path": "/etc/passwd"},
            working_dir=Path("."),
        )
    )
    assert not decision.should_skip


def test_plan_permission_hook_blocks_shell() -> None:
    hook = PlanPermissionHook(profile=AgentProfile.PLAN)
    decision = hook.before_tool_execution(
        ToolExecContext(
            snapshot=_snap(),
            tool_name="shell",
            arguments={"command": "ls"},
            working_dir=Path("."),
        )
    )
    assert decision.should_skip


def test_truncate_tool_output_hook() -> None:
    hook = TruncateToolOutputHook(max_chars=20)
    decision = hook.after_tool_execution(
        AfterToolContext(
            snapshot=_snap(),
            tool_name="file_read",
            tool_output="x" * 50,
            success=True,
        )
    )
    assert decision.modified_output is not None
    assert "truncated by AfterTool hook" in decision.modified_output
    assert decision.modified_output.startswith("x" * 20)


def test_build_default_hooks_includes_after() -> None:
    from secretary.agent.hook_policies import HooksConfig

    before, after = build_default_hooks(HooksConfig(), profile=AgentProfile.BUILD)
    assert before
    assert after
