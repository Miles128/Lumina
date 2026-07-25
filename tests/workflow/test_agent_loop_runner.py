"""Workflow agent node: mode=llm vs mode=agent (AgentLoop)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import LoopResult, PendingConfirmation
from secretary.workflow.pause import WorkflowNodePaused
from secretary.workflow.runners import build_agent_runner


def _llm() -> LlmConfig:
    return LlmConfig(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        source="test",
    )


def test_mode_llm_uses_chat_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "secretary.workflow.runners.chat_completion",
        lambda *a, **k: '{"summary": "hello"}',
    )
    runner = build_agent_runner(_llm())
    out = runner("say hi", {}, {"mode": "llm"})
    assert out["summary"] == "hello"


def test_mode_agent_runs_turn_and_returns_reply() -> None:
    turn_runner = MagicMock()
    turn_runner.run_agent_turn.return_value = LoopResult(
        reply="done via tools",
        steps=[],
        used_tools=["list_dir"],
        total_steps=2,
    )
    runner = build_agent_runner(_llm(), turn_runner=turn_runner, working_dir=Path("."))
    out = runner("list root", {}, {"mode": "agent", "profile": "ask"})
    assert out["summary"] == "done via tools"
    assert out["used_tools"] == ["list_dir"]
    turn_runner.run_agent_turn.assert_called_once()


def test_mode_agent_pauses_on_pending_confirmation() -> None:
    turn_runner = MagicMock()
    pending = PendingConfirmation(
        action_id="a1",
        tool_name="file_write",
        arguments={"path": "x.txt", "content": "hi"},
        description="Write x.txt",
        risk_level="medium",
        confirmation_kind="write_new",
    )
    turn_runner.run_agent_turn.return_value = LoopResult(
        reply="",
        steps=[],
        used_tools=[],
        total_steps=1,
        pending_confirmation=pending,
        messages_snapshot=[{"role": "user", "content": "write"}],
    )
    runner = build_agent_runner(_llm(), turn_runner=turn_runner, working_dir=Path("."))
    with pytest.raises(WorkflowNodePaused) as excinfo:
        runner("write file", {}, {"mode": "agent", "profile": "build"})
    assert excinfo.value.pause_kind == "tool_confirm"
    assert excinfo.value.agent_state["pending"]["tool_name"] == "file_write"


def test_agent_resume_after_tool_confirm() -> None:
    turn_runner = MagicMock()
    turn_runner.run_confirmed_action.return_value = LoopResult(
        reply="wrote ok",
        steps=[],
        used_tools=["file_write"],
        total_steps=2,
    )
    resume = build_agent_runner(
        _llm(), turn_runner=turn_runner, working_dir=Path(".")
    ).resume  # type: ignore[attr-defined]
    state = {
        "messages": [{"role": "user", "content": "write"}],
        "pending": {
            "action_id": "a1",
            "tool_name": "file_write",
            "arguments": {"path": "x.txt", "content": "hi"},
            "description": "Write x.txt",
            "risk_level": "medium",
            "confirmation_kind": "write_new",
        },
        "profile": "build",
        "max_steps": 12,
    }
    out = resume(state, {"approved": True})
    assert out["summary"] == "wrote ok"
    turn_runner.run_confirmed_action.assert_called_once()


def test_scheduler_propagates_tool_confirm_pause(tmp_path: Path) -> None:
    from secretary.workflow.models import WorkflowDef, WorkflowNode
    from secretary.workflow.scheduler import WorkflowScheduler

    def agent_runner(prompt: str, inputs: dict[str, Any], config: dict[str, Any] | None = None):
        raise WorkflowNodePaused(
            pause_prompt="Write x?",
            pause_kind="tool_confirm",
            agent_state={"pending": {"tool_name": "file_write"}, "messages": []},
        )

    sched = WorkflowScheduler(agent_runner=agent_runner)
    wf = WorkflowDef(
        name="t",
        nodes=[
            WorkflowNode(
                id="a",
                kind="agent",
                config={"mode": "agent", "prompt_template": "go"},
            )
        ],
    )
    result = sched.run(wf)
    assert result.status == "paused"
    assert result.pause_kind == "tool_confirm"
    assert result.checkpoint.get("agent_state", {}).get("pending", {}).get("tool_name") == (
        "file_write"
    )


def test_scheduler_resumes_agent_state_via_runner_resume() -> None:
    from secretary.workflow.models import WorkflowDef, WorkflowNode
    from secretary.workflow.scheduler import WorkflowScheduler

    calls: list[str] = []

    def agent_runner(prompt: str, inputs: dict[str, Any], config: dict[str, Any] | None = None):
        calls.append("run")
        raise WorkflowNodePaused(
            pause_prompt="Write x?",
            pause_kind="tool_confirm",
            agent_state={
                "pending": {"tool_name": "file_write", "action_id": "a1"},
                "messages": [{"role": "user", "content": "x"}],
            },
        )

    def agent_resume(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        calls.append("resume")
        assert state["pending"]["tool_name"] == "file_write"
        assert payload.get("approved") is True
        return {"summary": "ok"}

    sched = WorkflowScheduler(agent_runner=agent_runner, agent_resume=agent_resume)
    wf = WorkflowDef(
        name="t",
        nodes=[
            WorkflowNode(
                id="a",
                kind="agent",
                config={"mode": "agent", "prompt_template": "go"},
            )
        ],
    )
    paused = sched.run(wf)
    assert paused.status == "paused"
    done = sched.run(
        wf,
        checkpoint=paused.checkpoint,
        resume_payload={"approved": True},
    )
    assert done.status == "completed"
    assert done.node_outputs["a"]["summary"] == "ok"
    assert calls == ["run", "resume"]
