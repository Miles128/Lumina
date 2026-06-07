"""Base types shared between loop.py and tools modules (avoid circular imports)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


def _resolve_path(raw: str, working_dir: Path) -> Path:
    path = Path(raw or ".")
    if not path.is_absolute():
        path = working_dir / path
    return path.resolve()


class Tool:
    name: str = ""
    description: str = ""
    needs_confirmation: bool = False
    risk_level: str = "low"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._parameters(),
            "needs_confirmation": self.needs_confirmation,
        }

    def _parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        raise NotImplementedError

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"Execute {self.name}"
