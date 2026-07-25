"""WorkflowScheduler — topology, skill/agent/branch(expr)."""

from __future__ import annotations

from typing import Any

import pytest

from secretary.workflow.models import WorkflowDef, WorkflowEdge, WorkflowNode
from secretary.workflow.scheduler import (
    WorkflowRunError,
    WorkflowScheduler,
    topological_order,
)


def test_topological_order_linear() -> None:
    nodes = [
        WorkflowNode(id="a", kind="skill"),
        WorkflowNode(id="b", kind="agent"),
        WorkflowNode(id="c", kind="agent"),
    ]
    edges = [
        WorkflowEdge(from_id="a", to_id="b"),
        WorkflowEdge(from_id="b", to_id="c"),
    ]
    assert topological_order(nodes, edges) == ["a", "b", "c"]


def test_topological_order_rejects_cycle() -> None:
    nodes = [
        WorkflowNode(id="a", kind="skill"),
        WorkflowNode(id="b", kind="agent"),
    ]
    edges = [
        WorkflowEdge(from_id="a", to_id="b"),
        WorkflowEdge(from_id="b", to_id="a"),
    ]
    with pytest.raises(WorkflowRunError):
        topological_order(nodes, edges)


def test_scheduler_runs_linear_skill_then_agent() -> None:
    wf = WorkflowDef(
        name="demo",
        nodes=[
            WorkflowNode(
                id="n1",
                kind="skill",
                config={"skill_name": "echo"},
                outputs_schema={"text": "string"},
            ),
            WorkflowNode(
                id="n2",
                kind="agent",
                config={"prompt_template": "wrap:{{n1.text}}"},
                outputs_schema={"summary": "string"},
            ),
        ],
        edges=[WorkflowEdge(from_id="n1", to_id="n2")],
    )

    def skill_runner(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        assert name == "echo"
        return {"text": inputs.get("topic", "")}

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        assert "wrap:hello" in prompt
        return {"summary": prompt}

    scheduler = WorkflowScheduler(skill_runner=skill_runner, agent_runner=agent_runner)
    result = scheduler.run(wf, inputs={"topic": "hello"})
    assert result.status == "completed"
    assert result.node_outputs["n1"]["text"] == "hello"
    assert "wrap:hello" in result.node_outputs["n2"]["summary"]
    assert [step.node_id for step in result.steps] == ["n1", "n2"]


def test_scheduler_human_review_pauses_and_resumes() -> None:
    wf = WorkflowDef(
        name="review",
        nodes=[
            WorkflowNode(
                id="a",
                kind="agent",
                config={"prompt_template": "hi"},
            ),
            WorkflowNode(
                id="gate",
                kind="human_review",
                config={"prompt": "ok?"},
            ),
            WorkflowNode(
                id="b",
                kind="agent",
                config={"prompt_template": "after"},
            ),
        ],
        edges=[
            WorkflowEdge(from_id="a", to_id="gate"),
            WorkflowEdge(from_id="gate", to_id="b"),
        ],
    )

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"reply": prompt}

    scheduler = WorkflowScheduler(agent_runner=agent_runner)
    paused = scheduler.run(wf, inputs={})
    assert paused.status == "paused"
    assert paused.pause_node_id == "gate"
    assert paused.pause_prompt == "ok?"

    done = scheduler.run(
        wf,
        inputs={},
        checkpoint=paused.checkpoint,
        resume_payload={"approved": True, "note": "lgtm"},
    )
    assert done.status == "completed"
    assert done.node_outputs["gate"]["approved"] is True
    assert "after" in done.node_outputs["b"]["reply"]


def test_scheduler_agent_confirm_before_pauses() -> None:
    wf = WorkflowDef(
        name="confirm",
        nodes=[
            WorkflowNode(
                id="w",
                kind="agent",
                config={
                    "confirm_before": True,
                    "confirm_prompt": "run?",
                    "prompt_template": "work",
                },
            ),
        ],
        edges=[],
    )
    calls: list[str] = []

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        calls.append(prompt)
        return {"reply": prompt}

    scheduler = WorkflowScheduler(agent_runner=agent_runner)
    paused = scheduler.run(wf)
    assert paused.status == "paused"
    assert paused.pause_kind == "confirm"
    assert calls == []

    done = scheduler.run(
        wf,
        checkpoint=paused.checkpoint,
        resume_payload={"approved": True},
    )
    assert done.status == "completed"
    assert calls == ["work"]


def test_scheduler_branch_expr_routes_port() -> None:
    wf = WorkflowDef(
        name="branch-demo",
        nodes=[
            WorkflowNode(
                id="src",
                kind="skill",
                config={"skill_name": "echo"},
                outputs_schema={"flag": "string"},
            ),
            WorkflowNode(
                id="br",
                kind="branch",
                config={
                    "condition": {
                        "type": "expr",
                        "path": "src.flag",
                        "op": "eq",
                        "value": "yes",
                    },
                    "ports": ["yes", "no"],
                    "true_port": "yes",
                    "false_port": "no",
                },
            ),
            WorkflowNode(
                id="yes_node",
                kind="agent",
                config={"prompt_template": "YES"},
                outputs_schema={"summary": "string"},
            ),
            WorkflowNode(
                id="no_node",
                kind="agent",
                config={"prompt_template": "NO"},
                outputs_schema={"summary": "string"},
            ),
        ],
        edges=[
            WorkflowEdge(from_id="src", to_id="br"),
            WorkflowEdge(from_id="br", to_id="yes_node", port="yes"),
            WorkflowEdge(from_id="br", to_id="no_node", port="no"),
        ],
    )

    def skill_runner(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"flag": "yes"}

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"summary": prompt}

    result = WorkflowScheduler(
        skill_runner=skill_runner, agent_runner=agent_runner
    ).run(wf, inputs={})
    assert result.status == "completed"
    assert "yes_node" in result.node_outputs
    assert "no_node" not in result.node_outputs


def test_scheduler_on_failure_continue() -> None:
    wf = WorkflowDef(
        name="fail-continue",
        nodes=[
            WorkflowNode(
                id="bad",
                kind="skill",
                config={"skill_name": "boom"},
                on_failure="continue",
            ),
            WorkflowNode(
                id="ok",
                kind="agent",
                config={"prompt_template": "done"},
                outputs_schema={"summary": "string"},
            ),
        ],
        edges=[WorkflowEdge(from_id="bad", to_id="ok")],
    )

    def skill_runner(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"summary": prompt}

    result = WorkflowScheduler(
        skill_runner=skill_runner, agent_runner=agent_runner
    ).run(wf, inputs={})
    assert result.status == "completed"
    assert result.node_outputs["ok"]["summary"] == "done"
    assert any(step.status == "failed" for step in result.steps)
