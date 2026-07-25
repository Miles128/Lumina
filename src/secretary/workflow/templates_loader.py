"""Ship demo workflow templates (V5) from package data."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from secretary.workflow.models import WorkflowDef


def list_templates() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    root = resources.files("secretary.workflow").joinpath("templates")
    if not root.is_dir():
        return items
    for path in sorted(root.iterdir()):
        if not path.name.endswith(".json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or path.stem)
        items.append(
            {
                "id": path.stem,
                "name": name,
                "version": int(data.get("version") or 1),
                "node_count": len(data.get("nodes") or []),
            }
        )
    return items


def load_template(template_id: str) -> WorkflowDef:
    cleaned = (template_id or "").strip()
    if not cleaned or "/" in cleaned or ".." in cleaned:
        raise ValueError(f"invalid template id: {template_id!r}")
    root = resources.files("secretary.workflow").joinpath("templates")
    path = root.joinpath(f"{cleaned}.json")
    if not path.is_file():
        raise FileNotFoundError(f"template not found: {cleaned}")
    data = json.loads(path.read_text(encoding="utf-8"))
    workflow = WorkflowDef.from_dict(data)
    if not workflow.name:
        workflow.name = cleaned
    return workflow
