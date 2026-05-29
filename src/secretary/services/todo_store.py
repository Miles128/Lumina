"""In-session task list persisted to disk."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from secretary.exceptions import SecretaryError


@dataclass(frozen=True)
class TodoItem:
    id: str
    content: str
    done: bool
    created_at: str


class TodoStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def list_items(self) -> list[TodoItem]:
        return self._load()

    def add(self, content: str) -> TodoItem:
        cleaned = content.strip()
        if not cleaned:
            raise SecretaryError("待办内容不能为空")
        items = self._load()
        item_id = f"t{len(items) + 1}"
        while any(item.id == item_id for item in items):
            item_id = f"{item_id}x"
        item = TodoItem(
            id=item_id,
            content=cleaned,
            done=False,
            created_at=datetime.now(UTC).isoformat(),
        )
        items.append(item)
        self._save(items)
        return item

    def complete(self, item_id: str) -> TodoItem:
        items = self._load()
        for index, item in enumerate(items):
            if item.id != item_id:
                continue
            updated = TodoItem(
                id=item.id,
                content=item.content,
                done=True,
                created_at=item.created_at,
            )
            items[index] = updated
            self._save(items)
            return updated
        raise SecretaryError(f"未找到待办：{item_id}")

    def remove(self, item_id: str) -> None:
        items = self._load()
        filtered = [item for item in items if item.id != item_id]
        if len(filtered) == len(items):
            raise SecretaryError(f"未找到待办：{item_id}")
        self._save(filtered)

    def clear_done(self) -> int:
        items = self._load()
        kept = [item for item in items if not item.done]
        removed = len(items) - len(kept)
        self._save(kept)
        return removed

    def _load(self) -> list[TodoItem]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        items: list[TodoItem] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            item_id = entry.get("id")
            content = entry.get("content")
            if not isinstance(item_id, str) or not isinstance(content, str):
                continue
            items.append(
                TodoItem(
                    id=item_id,
                    content=content.strip(),
                    done=bool(entry.get("done", False)),
                    created_at=str(entry.get("created_at", "")),
                )
            )
        return items

    def _save(self, items: list[TodoItem]) -> None:
        payload = [
            {
                "id": item.id,
                "content": item.content,
                "done": item.done,
                "created_at": item.created_at,
            }
            for item in items
        ]
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._path.write_text(text, encoding="utf-8")
