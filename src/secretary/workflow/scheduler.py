"""Deterministic workflow DAG scheduler (F26). No LLM in the scheduler itself."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from secretary.workflow.models import WorkflowDef, WorkflowEdge, WorkflowNode
from secretary.workflow.pause import WorkflowNodePaused

SkillRunner = Callable[[str, dict[str, Any]], dict[str, Any]]
# (prompt, inputs, config) — config may be omitted by legacy 2-arg callables
AgentRunner = Callable[..., dict[str, Any]]
AgentResume = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

_TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


class WorkflowRunError(ValueError):
    """Invalid workflow graph or fatal run failure."""


@dataclass
class NodeStepResult:
    node_id: str
    kind: str
    status: str  # completed | failed | skipped | paused
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class WorkflowRunResult:
    status: str  # completed | failed | paused
    steps: list[NodeStepResult] = field(default_factory=list)
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str = ""
    pause_node_id: str = ""
    pause_prompt: str = ""
    pause_kind: str = ""  # human_review | confirm
    checkpoint: dict[str, Any] = field(default_factory=dict)


def topological_order(
    nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
) -> list[str]:
    ids = [node.id for node in nodes]
    id_set = set(ids)
    if len(ids) != len(id_set):
        raise WorkflowRunError("duplicate node ids")
    incoming: dict[str, int] = {node_id: 0 for node_id in ids}
    outbound: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.from_id not in id_set or edge.to_id not in id_set:
            raise WorkflowRunError(f"edge references unknown node: {edge}")
        incoming[edge.to_id] += 1
        outbound[edge.from_id].append(edge.to_id)

    queue = deque([node_id for node_id, count in incoming.items() if count == 0])
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for child in outbound[node_id]:
            incoming[child] -= 1
            if incoming[child] == 0:
                queue.append(child)
    if len(ordered) != len(ids):
        raise WorkflowRunError("workflow contains a cycle")
    return ordered


class WorkflowScheduler:
    def __init__(
        self,
        *,
        skill_runner: SkillRunner | None = None,
        agent_runner: AgentRunner | None = None,
        agent_resume: AgentResume | None = None,
    ) -> None:
        self._skill_runner = skill_runner
        self._agent_runner = agent_runner
        self._agent_resume = agent_resume
        if agent_resume is None and agent_runner is not None:
            resume_fn = getattr(agent_runner, "resume", None)
            if callable(resume_fn):
                self._agent_resume = resume_fn

    def run(
        self,
        workflow: WorkflowDef,
        *,
        inputs: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        resume_payload: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        inputs = dict(inputs or {})
        order = topological_order(workflow.nodes, workflow.edges)
        by_id = {node.id: node for node in workflow.nodes}
        inbound: dict[str, list[WorkflowEdge]] = defaultdict(list)
        outbound: dict[str, list[WorkflowEdge]] = defaultdict(list)
        for edge in workflow.edges:
            inbound[edge.to_id].append(edge)
            outbound[edge.from_id].append(edge)

        activated: set[tuple[str, str, str]] = set()
        node_outputs: dict[str, dict[str, Any]] = {"__inputs__": inputs}
        steps: list[NodeStepResult] = []
        skip_until = ""

        if checkpoint:
            for key, value in (checkpoint.get("node_outputs") or {}).items():
                if isinstance(value, dict):
                    node_outputs[key] = dict(value)
            for item in checkpoint.get("steps") or []:
                if not isinstance(item, dict):
                    continue
                steps.append(
                    NodeStepResult(
                        node_id=str(item.get("node_id") or ""),
                        kind=str(item.get("kind") or ""),
                        status=str(item.get("status") or "completed"),
                        outputs=dict(item.get("outputs") or {}),
                        error=str(item.get("error") or ""),
                    )
                )
            for triple in checkpoint.get("activated") or []:
                if isinstance(triple, (list, tuple)) and len(triple) == 3:
                    activated.add((str(triple[0]), str(triple[1]), str(triple[2])))
            skip_until = str(checkpoint.get("pause_node_id") or "")

        for node_id in order:
            gate_cleared = False
            # Resume: skip until the paused node, then apply human decision
            if skip_until:
                if node_id != skip_until:
                    continue
                steps = [s for s in steps if not (s.node_id == node_id and s.status == "paused")]
                node = by_id[node_id]
                if resume_payload is None:
                    raise WorkflowRunError("resume_payload required for paused node")
                approved = bool(resume_payload.get("approved", True))
                note = str(resume_payload.get("note") or "")
                if not approved:
                    return WorkflowRunResult(
                        status="failed",
                        steps=steps
                        + [
                            NodeStepResult(
                                node_id=node_id,
                                kind=node.kind,
                                status="failed",
                                error="human rejected",
                                outputs={"approved": False, "note": note},
                            )
                        ],
                        node_outputs={
                            k: v for k, v in node_outputs.items() if k != "__inputs__"
                        },
                        error=f"node {node_id} rejected by human",
                    )
                agent_state = dict(checkpoint.get("agent_state") or {}) if checkpoint else {}
                if agent_state and node.kind == "agent":
                    if self._agent_resume is None:
                        raise WorkflowRunError("agent_resume is not configured")
                    try:
                        outputs = dict(self._agent_resume(agent_state, resume_payload))
                    except WorkflowNodePaused as paused:
                        return self._paused_result(
                            steps=steps,
                            node_outputs=node_outputs,
                            activated=activated,
                            inputs=inputs,
                            node_id=node_id,
                            kind=node.kind,
                            paused=paused,
                        )
                    steps.append(
                        NodeStepResult(
                            node_id=node_id,
                            kind=node.kind,
                            status="completed",
                            outputs=outputs,
                        )
                    )
                    node_outputs[node_id] = outputs
                    for edge in outbound.get(node_id, []):
                        activated.add((edge.from_id, edge.to_id, edge.port))
                    skip_until = ""
                    resume_payload = None
                    continue
                if node.kind == "human_review":
                    outputs = {"approved": True, "note": note}
                    steps.append(
                        NodeStepResult(
                            node_id=node_id,
                            kind=node.kind,
                            status="completed",
                            outputs=outputs,
                        )
                    )
                    node_outputs[node_id] = outputs
                    for edge in outbound.get(node_id, []):
                        activated.add((edge.from_id, edge.to_id, edge.port))
                    skip_until = ""
                    resume_payload = None
                    continue
                # agent + confirm_before: cleared gate, execute agent body
                gate_cleared = True
                skip_until = ""
                resume_payload = None

            node = by_id[node_id]
            edges_in = inbound.get(node_id, [])
            if edges_in:
                active_in = [
                    edge
                    for edge in edges_in
                    if (edge.from_id, edge.to_id, edge.port) in activated
                ]
                if not active_in:
                    steps.append(
                        NodeStepResult(node_id=node_id, kind=node.kind, status="skipped")
                    )
                    continue
            else:
                active_in = []

            # Pause points: human_review, or agent with confirm_before (first hit)
            needs_pause = (
                not gate_cleared
                and (
                    node.kind == "human_review"
                    or (node.kind == "agent" and bool(node.config.get("confirm_before")))
                )
            )
            already_done = any(
                s.node_id == node_id and s.status == "completed" for s in steps
            )
            if needs_pause and not already_done:
                prompt = str(
                    node.config.get("prompt")
                    or node.config.get("confirm_prompt")
                    or ("请确认后继续" if node.kind != "human_review" else "请人工审阅后继续")
                )
                pause_kind = "human_review" if node.kind == "human_review" else "confirm"
                return self._paused_result(
                    steps=steps,
                    node_outputs=node_outputs,
                    activated=activated,
                    inputs=inputs,
                    node_id=node_id,
                    kind=node.kind,
                    pause_prompt=prompt,
                    pause_kind=pause_kind,
                )

            try:
                outputs = self._execute_node(node, inputs, node_outputs)
            except WorkflowNodePaused as paused:
                return self._paused_result(
                    steps=steps,
                    node_outputs=node_outputs,
                    activated=activated,
                    inputs=inputs,
                    node_id=node_id,
                    kind=node.kind,
                    paused=paused,
                )
            except Exception as exc:
                step = NodeStepResult(
                    node_id=node_id,
                    kind=node.kind,
                    status="failed",
                    error=str(exc),
                )
                steps.append(step)
                if node.on_failure != "continue":
                    return WorkflowRunResult(
                        status="failed",
                        steps=steps,
                        node_outputs={
                            key: value
                            for key, value in node_outputs.items()
                            if key != "__inputs__"
                        },
                        error=f"node {node_id} failed: {exc}",
                    )
                outputs = {}
            else:
                steps.append(
                    NodeStepResult(
                        node_id=node_id,
                        kind=node.kind,
                        status="completed",
                        outputs=outputs,
                    )
                )

            node_outputs[node_id] = outputs
            chosen_port: str | None = None
            if node.kind == "branch":
                chosen_port = str(outputs.get("port") or "")

            for edge in outbound.get(node_id, []):
                if chosen_port is None or edge.port == chosen_port:
                    activated.add((edge.from_id, edge.to_id, edge.port))

        return WorkflowRunResult(
            status="completed",
            steps=steps,
            node_outputs={
                key: value for key, value in node_outputs.items() if key != "__inputs__"
            },
        )

    def _execute_node(
        self,
        node: WorkflowNode,
        workflow_inputs: dict[str, Any],
        node_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        mapped = self._map_inputs(node, workflow_inputs, node_outputs)
        if node.kind == "skill":
            if self._skill_runner is None:
                raise WorkflowRunError("skill_runner is not configured")
            skill_name = str(node.config.get("skill_name") or "").strip()
            if not skill_name:
                raise WorkflowRunError(f"node {node.id}: missing skill_name")
            return dict(self._skill_runner(skill_name, mapped))

        if node.kind == "agent":
            if self._agent_runner is None:
                raise WorkflowRunError("agent_runner is not configured")
            template = str(node.config.get("prompt_template") or "")
            prompt = _render_template(template, workflow_inputs, node_outputs)
            try:
                result = self._agent_runner(prompt, mapped, dict(node.config))
            except TypeError:
                result = self._agent_runner(prompt, mapped)
            return dict(result)

        if node.kind == "branch":
            return self._eval_branch(node, workflow_inputs, node_outputs)

        if node.kind == "human_review":
            # Should be handled by pause/resume path before execute
            return {
                "approved": True,
                "note": str(node.config.get("default_note") or ""),
            }

        raise WorkflowRunError(f"unsupported node kind: {node.kind}")

    def _paused_result(
        self,
        *,
        steps: list[NodeStepResult],
        node_outputs: dict[str, dict[str, Any]],
        activated: set[tuple[str, str, str]],
        inputs: dict[str, Any],
        node_id: str,
        kind: str,
        pause_prompt: str = "",
        pause_kind: str = "",
        paused: WorkflowNodePaused | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        prompt = pause_prompt
        kind_name = pause_kind
        state = dict(agent_state or {})
        if paused is not None:
            prompt = paused.pause_prompt
            kind_name = paused.pause_kind
            state = dict(paused.agent_state)
        steps = list(steps) + [
            NodeStepResult(
                node_id=node_id,
                kind=kind,
                status="paused",
                outputs={"prompt": prompt},
            )
        ]
        public_outputs = {k: v for k, v in node_outputs.items() if k != "__inputs__"}
        checkpoint: dict[str, Any] = {
            "node_outputs": public_outputs,
            "steps": [
                {
                    "node_id": s.node_id,
                    "kind": s.kind,
                    "status": s.status,
                    "outputs": s.outputs,
                    "error": s.error,
                }
                for s in steps
            ],
            "activated": [list(item) for item in activated],
            "pause_node_id": node_id,
            "inputs": inputs,
        }
        if state:
            checkpoint["agent_state"] = state
        return WorkflowRunResult(
            status="paused",
            steps=steps,
            node_outputs=public_outputs,
            pause_node_id=node_id,
            pause_prompt=prompt,
            pause_kind=kind_name,
            checkpoint=checkpoint,
        )

    def _map_inputs(
        self,
        node: WorkflowNode,
        workflow_inputs: dict[str, Any],
        node_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if not node.inputs_schema:
            return dict(workflow_inputs)
        mapped: dict[str, Any] = {}
        for key in node.inputs_schema:
            mapped[key] = _resolve_path(str(key), workflow_inputs, node_outputs)
        # Also pass top-level workflow inputs for convenience (skill echo topic).
        for key, value in workflow_inputs.items():
            mapped.setdefault(key, value)
        return mapped

    def _eval_branch(
        self,
        node: WorkflowNode,
        workflow_inputs: dict[str, Any],
        node_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        condition = dict(node.config.get("condition") or {})
        cond_type = str(condition.get("type") or "expr")
        if cond_type != "expr":
            raise WorkflowRunError(
                f"node {node.id}: branch type {cond_type!r} not in v1 (expr only)"
            )
        path = str(condition.get("path") or "")
        op = str(condition.get("op") or "eq")
        expected = condition.get("value")
        actual = _resolve_path(path, workflow_inputs, node_outputs)
        matched = _compare(actual, op, expected)
        true_port = str(node.config.get("true_port") or "true")
        false_port = str(node.config.get("false_port") or "false")
        ports = list(node.config.get("ports") or [true_port, false_port])
        if true_port not in ports:
            ports.append(true_port)
        if false_port not in ports:
            ports.append(false_port)
        port = true_port if matched else false_port
        return {"port": port, "matched": matched, "actual": actual}


def _resolve_path(
    path: str,
    workflow_inputs: dict[str, Any],
    node_outputs: dict[str, dict[str, Any]],
) -> Any:
    cleaned = path.strip()
    if not cleaned:
        return None
    if "." not in cleaned:
        if cleaned in workflow_inputs:
            return workflow_inputs[cleaned]
        # bare field may live on a single upstream — not guessed here
        return workflow_inputs.get(cleaned)
    node_id, _, field = cleaned.partition(".")
    bucket = node_outputs.get(node_id) or {}
    return bucket.get(field)


def _render_template(
    template: str,
    workflow_inputs: dict[str, Any],
    node_outputs: dict[str, dict[str, Any]],
) -> str:
    def repl(match: re.Match[str]) -> str:
        value = _resolve_path(match.group(1), workflow_inputs, node_outputs)
        return "" if value is None else str(value)

    return _TEMPLATE_RE.sub(repl, template)


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "eq":
        return bool(actual == expected)
    if op == "neq":
        return bool(actual != expected)
    if op == "contains":
        return expected in (actual or "")
    raise WorkflowRunError(f"unsupported branch op: {op}")
