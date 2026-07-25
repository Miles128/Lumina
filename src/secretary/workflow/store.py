"""Persist workflow definitions under ~/.lumina/workflows/."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from secretary.workflow.models import WorkflowDef

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class WorkflowStoreError(ValueError):
    """Invalid workflow name or missing definition."""


class WorkflowStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def list_names(self) -> list[str]:
        names = [path.stem for path in self._root.glob("*.json") if path.is_file()]
        return sorted(names)

    def get(self, name: str) -> WorkflowDef:
        path = self._path_for(name)
        if not path.is_file():
            raise WorkflowStoreError(f"workflow not found: {name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        workflow = WorkflowDef.from_dict(data)
        if not workflow.name:
            workflow.name = name
        return workflow

    def save(self, workflow: WorkflowDef) -> None:
        name = self._validate_name(workflow.name)
        path = self._path_for(name)
        path.write_text(
            json.dumps(workflow.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def delete(self, name: str) -> None:
        path = self._path_for(name)
        if not path.is_file():
            raise WorkflowStoreError(f"workflow not found: {name}")
        path.unlink()

    def save_run(self, run_id: str, payload: dict[str, Any]) -> Path:
        runs_dir = self._root / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{run_id}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def get_run(self, run_id: str) -> dict[str, Any]:
        cleaned = (run_id or "").strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned or ".." in cleaned:
            raise WorkflowStoreError(f"invalid run id: {run_id!r}")
        path = self._root / "runs" / f"{cleaned}.json"
        if not path.is_file():
            raise WorkflowStoreError(f"run not found: {run_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise WorkflowStoreError(f"corrupt run: {run_id}")
        return data

    def _path_for(self, name: str) -> Path:
        safe = self._validate_name(name)
        return self._root / f"{safe}.json"

    def _validate_name(self, name: str) -> str:
        cleaned = (name or "").strip()
        if not _NAME_RE.fullmatch(cleaned):
            raise WorkflowStoreError(f"invalid workflow name: {name!r}")
        return cleaned
