"""Workflow DAG models (F26)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowNode:
    id: str
    kind: str  # "skill" | "agent" | "branch" | "human_review"
    config: dict[str, Any] = field(default_factory=dict)
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)
    on_failure: str = "stop"  # "stop" | "continue"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "config": self.config,
            "inputs_schema": self.inputs_schema,
            "outputs_schema": self.outputs_schema,
            "on_failure": self.on_failure,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowNode:
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind", "agent")),
            config=dict(data.get("config") or {}),
            inputs_schema=dict(data.get("inputs_schema") or {}),
            outputs_schema=dict(data.get("outputs_schema") or {}),
            on_failure=str(data.get("on_failure") or "stop"),
        )


@dataclass
class WorkflowEdge:
    from_id: str
    to_id: str
    port: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {"from": self.from_id, "to": self.to_id, "port": self.port}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowEdge:
        return cls(
            from_id=str(data["from"]),
            to_id=str(data["to"]),
            port=str(data.get("port") or "default"),
        )


@dataclass
class WorkflowDef:
    name: str
    version: int = 1
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "inputs_schema": self.inputs_schema,
            "outputs_schema": self.outputs_schema,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowDef:
        return cls(
            name=str(data.get("name") or ""),
            version=int(data.get("version") or 1),
            inputs_schema=dict(data.get("inputs_schema") or {}),
            outputs_schema=dict(data.get("outputs_schema") or {}),
            nodes=[WorkflowNode.from_dict(item) for item in data.get("nodes") or []],
            edges=[WorkflowEdge.from_dict(item) for item in data.get("edges") or []],
        )
