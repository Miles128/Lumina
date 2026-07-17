"""Base class for JSON-backed Pydantic config stores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from secretary.exceptions import SecretaryError

T = TypeVar("T", bound=BaseModel)


class BaseJsonConfigStore(Generic[T]):
    """Shared read/write helpers for JSON config files."""

    def __init__(self, path: Path, *, ensure_parent: bool = True) -> None:
        self._path = path
        if ensure_parent:
            path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def _read_json_or_none(self) -> dict[str, object] | None:
        """Read and parse JSON. Return None if file does not exist."""
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretaryError(f"invalid config: {self._path}") from exc
        if not isinstance(raw, dict):
            raise SecretaryError(f"invalid config (not a JSON object): {self._path}")
        return raw

    def _write_json(
        self,
        document: T,
        *,
        exclude_none: bool = False,
        trailing_newline: bool = True,
    ) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = document.model_dump_json(
            indent=2,
            ensure_ascii=False,
            exclude_none=exclude_none,
        )
        if trailing_newline:
            text += "\n"
        self._path.write_text(text, encoding="utf-8")
