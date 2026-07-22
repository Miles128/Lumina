"""Unit tests for desktop workflow_graph conversion helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

GRAPH_JS = Path(__file__).resolve().parents[2] / "desktop" / "ui" / "workflow_graph.js"


def _node_eval(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def test_workflow_roundtrip_preserves_ids_and_edges() -> None:
    script = f"""
const g = require({str(GRAPH_JS)!r});
const wf = {{
  name: "demo",
  version: 1,
  inputs_schema: {{ topic: {{ type: "string" }} }},
  outputs_schema: {{}},
  nodes: [
    {{ id: "a", kind: "agent", config: {{ prompt_template: "hi", _canvas: {{ x: 10, y: 20 }} }}, inputs_schema: {{}}, outputs_schema: {{}}, on_failure: "stop" }},
    {{ id: "b", kind: "agent", config: {{ prompt_template: "bye" }}, inputs_schema: {{}}, outputs_schema: {{}}, on_failure: "stop" }},
  ],
  edges: [{{ from: "a", to: "b", port: "default" }}],
}};
const df = g.workflowToDrawflow(wf);
const back = g.drawflowToWorkflow(df, {{ name: wf.name, version: wf.version, inputs_schema: wf.inputs_schema, outputs_schema: wf.outputs_schema }});
const ids = back.nodes.map((n) => n.id).sort().join(",");
const edge = back.edges.map((e) => e.from + "->" + e.to + ":" + e.port).join("|");
const ax = back.nodes.find((n) => n.id === "a").config._canvas.x;
console.log(ids + "|" + edge + "|" + ax);
"""
    out = _node_eval(script)
    assert out == "a,b|a->b:default|10"


def test_branch_ports_roundtrip() -> None:
    script = f"""
const g = require({str(GRAPH_JS)!r});
const wf = {{
  name: "br",
  version: 1,
  nodes: [
    {{ id: "src", kind: "skill", config: {{ skill_name: "echo" }}, inputs_schema: {{}}, outputs_schema: {{}}, on_failure: "stop" }},
    {{ id: "br", kind: "branch", config: {{ condition: {{ type: "expr", path: "flag", op: "eq", value: "yes" }}, true_port: "yes", false_port: "no", ports: ["yes", "no"] }}, inputs_schema: {{}}, outputs_schema: {{}}, on_failure: "stop" }},
    {{ id: "yes_n", kind: "agent", config: {{ prompt_template: "Y" }}, inputs_schema: {{}}, outputs_schema: {{}}, on_failure: "stop" }},
    {{ id: "no_n", kind: "agent", config: {{ prompt_template: "N" }}, inputs_schema: {{}}, outputs_schema: {{}}, on_failure: "stop" }},
  ],
  edges: [
    {{ from: "src", to: "br", port: "default" }},
    {{ from: "br", to: "yes_n", port: "yes" }},
    {{ from: "br", to: "no_n", port: "no" }},
  ],
}};
const df = g.workflowToDrawflow(wf);
const back = g.drawflowToWorkflow(df, {{ name: "br", version: 1 }});
const ports = back.edges.filter((e) => e.from === "br").map((e) => e.to + ":" + e.port).sort().join(",");
console.log(ports);
"""
    out = _node_eval(script)
    assert out == "no_n:no,yes_n:yes"
