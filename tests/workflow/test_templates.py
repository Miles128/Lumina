"""V5 workflow templates."""

from __future__ import annotations

from secretary.workflow.templates_loader import list_templates, load_template


def test_list_and_load_bundled_templates() -> None:
    items = list_templates()
    ids = {item["id"] for item in items}
    assert "research" in ids
    assert "code_change" in ids
    wf = load_template("research")
    assert wf.name == "research"
    kinds = {node.kind for node in wf.nodes}
    assert "human_review" in kinds
