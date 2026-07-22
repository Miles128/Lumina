"""WorkflowStore CRUD — F26 slice E."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.workflow.models import WorkflowDef, WorkflowEdge, WorkflowNode
from secretary.workflow.store import WorkflowStore, WorkflowStoreError


def _sample_workflow(name: str = "search-and-summarize") -> WorkflowDef:
    return WorkflowDef(
        name=name,
        version=1,
        inputs_schema={"topic": {"type": "string"}},
        outputs_schema={"summary": {"type": "string"}},
        nodes=[
            WorkflowNode(
                id="n1",
                kind="skill",
                config={"skill_name": "web_search"},
                inputs_schema={"query": "string"},
                outputs_schema={"results": "array"},
            ),
            WorkflowNode(
                id="n2",
                kind="agent",
                config={"prompt_template": "总结：{{n1.results}}"},
                inputs_schema={"n1.results": "array"},
                outputs_schema={"summary": "string"},
            ),
        ],
        edges=[WorkflowEdge(from_id="n1", to_id="n2", port="default")],
    )


def test_save_and_get_workflow(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows")
    wf = _sample_workflow()
    store.save(wf)

    loaded = store.get("search-and-summarize")
    assert loaded.name == "search-and-summarize"
    assert len(loaded.nodes) == 2
    assert loaded.edges[0].from_id == "n1"
    assert (tmp_path / "workflows" / "search-and-summarize.json").is_file()


def test_list_workflows(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows")
    store.save(_sample_workflow("a"))
    store.save(_sample_workflow("b"))
    names = store.list_names()
    assert names == ["a", "b"]


def test_delete_workflow(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows")
    store.save(_sample_workflow())
    store.delete("search-and-summarize")
    with pytest.raises(WorkflowStoreError):
        store.get("search-and-summarize")


def test_get_missing_raises(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows")
    with pytest.raises(WorkflowStoreError):
        store.get("missing")


def test_rejects_invalid_name(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "workflows")
    with pytest.raises(WorkflowStoreError):
        store.save(_sample_workflow("../evil"))
