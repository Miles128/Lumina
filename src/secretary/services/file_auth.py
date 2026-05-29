"""Persistent read grant and per-session write-new grant."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from secretary.exceptions import SecretaryError

WriteConfirmationKind = Literal["write_new", "write_modify", "write_delete"]


@dataclass(frozen=True)
class FileAuthDocument:
    permanent_read: bool = False


class FileAuthService:
    def __init__(self, auth_path: Path) -> None:
        self._path = auth_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._session_write_new = False
        self._document = self._load()

    def has_permanent_read(self) -> bool:
        return self._document.permanent_read

    def grant_permanent_read(self) -> None:
        self._document = FileAuthDocument(permanent_read=True)
        self._save()

    def revoke_permanent_read(self) -> None:
        self._document = FileAuthDocument(permanent_read=False)
        self._save()

    def has_session_write_new(self) -> bool:
        return self._session_write_new

    def grant_session_write_new(self) -> None:
        self._session_write_new = True

    def clear_session_write_new(self) -> None:
        self._session_write_new = False

    def needs_read_confirmation(self) -> bool:
        return not self._document.permanent_read

    def write_confirmation_kind(self, path: Path, *, append: bool = False) -> WriteConfirmationKind:
        _ = append
        if path.exists():
            return "write_modify"
        return "write_new"

    def needs_write_confirmation(self, path: Path, *, append: bool) -> bool:
        kind = self.write_confirmation_kind(path, append=append)
        if kind == "write_new":
            return not self._session_write_new
        return True

    def _load(self) -> FileAuthDocument:
        if not self._path.exists():
            return FileAuthDocument()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SecretaryError("文件授权配置损坏") from error
        if not isinstance(raw, dict):
            return FileAuthDocument()
        return FileAuthDocument(permanent_read=bool(raw.get("permanent_read", False)))

    def _save(self) -> None:
        payload = {"permanent_read": self._document.permanent_read}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._path.write_text(text, encoding="utf-8")
