"""Tests for aisuite pause-on-approval → LoopResult mapping."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from aisuite import ToolPolicyContext, ToolPolicyDecision

from secretary.agent.aisuite_runtime import (
    pause_approval_policy,
    run_result_to_loop_result,
    split_system_and_input,
)


def test_pause_approval_policy_sets_pause_metadata() -> None:
    policy = pause_approval_policy(lambda name, args: name == "shell")
    ctx = ToolPolicyContext(
        agent_name="lumina",
        tool_name="shell",
        arguments={"command": "ls"},
        run_name=None,
        trace_id=None,
        group_id=None,
        tags=[],
        metadata={},
        messages=[],
    )
    decision = policy.evaluate(ctx)
    assert isinstance(decision, ToolPolicyDecision)
    assert decision.allowed is False
    assert decision.metadata.get("pause_for_approval") is True


def test_run_result_requires_input_maps_pending(tmp_path: Path) -> None:
    result = SimpleNamespace(
        status="requires_input",
        metadata={
            "pending_approval": {
                "name": "shell",
                "arguments": {"command": "rm -rf /"},
                "reason": "needs_human_approval",
            }
        },
        steps=[],
        messages=[{"role": "user", "content": "hi"}],
        final_output=None,
    )
    loop = run_result_to_loop_result(
        result,
        tools_by_name={},
        working_dir=tmp_path,
    )
    assert loop.pending_confirmation is not None
    assert loop.pending_confirmation.tool_name == "shell"
    assert loop.pending_confirmation.arguments["command"] == "rm -rf /"
    assert loop.messages_snapshot == [{"role": "user", "content": "hi"}]


def test_split_system_and_input() -> None:
    instructions, rest = split_system_and_input(
        [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hi"},
        ]
    )
    assert instructions == "be helpful"
    assert rest == [{"role": "user", "content": "hi"}]
