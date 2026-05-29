"""User-edited profile persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class UserProfileDocument(BaseModel):
    markdown: str = ""
    updated_at: datetime | None = None


class UserProfileStore:
    def __init__(self, profile_path: Path) -> None:
        self._path = profile_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> UserProfileDocument:
        if not self._path.exists():
            return UserProfileDocument()
        text = self._path.read_text(encoding="utf-8")
        if not text.strip():
            return UserProfileDocument()
        return UserProfileDocument(
            markdown=text,
            updated_at=datetime.fromtimestamp(self._path.stat().st_mtime, tz=UTC),
        )

    def save(self, markdown: str) -> UserProfileDocument:
        cleaned = markdown.strip()
        if cleaned:
            self._path.write_text(cleaned + "\n", encoding="utf-8")
        elif self._path.exists():
            self._path.unlink()
        return self.load()

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
