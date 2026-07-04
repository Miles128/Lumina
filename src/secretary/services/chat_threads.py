"""Persistent chat threads (multi-session UI + agent history per thread)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_THREAD_MESSAGES = 400
MAX_HISTORY_MESSAGES = 64


@dataclass
class ChatThread:
    id: str
    title: str = "新对话"
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    messages: list[dict[str, str]] = field(default_factory=list)


class ChatThreadStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load_document(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"current_id": "", "threads": []}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"current_id": "", "threads": []}
        threads = payload.get("threads")
        if not isinstance(threads, list):
            threads = []
        return {
            "current_id": str(payload.get("current_id") or ""),
            "threads": threads,
        }

    def save_document(self, *, current_id: str, threads: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "current_id": current_id,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "threads": threads,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def list_view(self) -> dict[str, Any]:
        document = self.load_document()
        return {
            "current_id": document["current_id"],
            "threads": document["threads"],
            "path": str(self._path),
        }

    def create_thread(self, *, title: str = "新对话") -> dict[str, Any]:
        document = self.load_document()
        threads = [item for item in document["threads"] if isinstance(item, dict)]
        thread_id = f"t_{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC).isoformat()
        threads.insert(
            0,
            {
                "id": thread_id,
                "title": (title or "新对话")[:120],
                "updatedAt": now,
                "messages": [],
            },
        )
        self.save_document(current_id=thread_id, threads=threads)
        return self.list_view()

    def set_current(self, thread_id: str) -> dict[str, Any]:
        document = self.load_document()
        threads = [item for item in document["threads"] if isinstance(item, dict)]
        current = thread_id if any(item.get("id") == thread_id for item in threads) else document["current_id"]
        if not current and threads:
            current = str(threads[0].get("id") or "")
        self.save_document(current_id=current, threads=threads)
        return self.list_view()

    def delete_thread(self, thread_id: str) -> dict[str, Any]:
        document = self.load_document()
        threads = [
            item
            for item in document["threads"]
            if isinstance(item, dict) and item.get("id") != thread_id
        ]
        current = str(document["current_id"] or "")
        if current == thread_id:
            current = str(threads[0].get("id") or "") if threads else ""
        self.save_document(current_id=current, threads=threads)
        if not threads:
            return self.create_thread()
        return self.list_view()

    def replace_all(self, *, current_id: str, threads: list[dict[str, Any]]) -> dict[str, Any]:
        cleaned: list[dict[str, Any]] = []
        for item in threads:
            if not isinstance(item, dict):
                continue
            thread_id = str(item.get("id") or "").strip()
            if not thread_id:
                thread_id = f"t_{uuid.uuid4().hex[:10]}"
            messages = item.get("messages")
            if not isinstance(messages, list):
                messages = []
            normalized_messages: list[dict[str, str]] = []
            for message in messages[-MAX_THREAD_MESSAGES:]:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                text = message.get("text") or message.get("content")
                if role in {"user", "assistant", "bot"} and isinstance(text, str) and text.strip():
                    normalized_role = "assistant" if role == "bot" else role
                    normalized_messages.append({"role": normalized_role, "text": text.strip()})
            cleaned.append(
                {
                    "id": thread_id,
                    "title": str(item.get("title") or "新对话")[:120],
                    "updatedAt": str(item.get("updatedAt") or item.get("updated_at") or datetime.now(UTC).isoformat()),
                    "messages": normalized_messages,
                }
            )
        current = current_id if any(t["id"] == current_id for t in cleaned) else (cleaned[0]["id"] if cleaned else "")
        self.save_document(current_id=current, threads=cleaned)
        return self.list_view()

    def agent_history(self, thread_id: str) -> list[dict[str, str]]:
        document = self.load_document()
        for item in document["threads"]:
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            messages = item.get("messages")
            if not isinstance(messages, list):
                return []
            history: list[dict[str, str]] = []
            for message in messages[-MAX_HISTORY_MESSAGES:]:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                text = message.get("text") or message.get("content")
                if role in {"user", "assistant", "bot"} and isinstance(text, str) and text.strip():
                    normalized = "assistant" if role == "bot" else str(role)
                    history.append({"role": normalized, "content": text.strip()})
            return history
        return []

    def append_turn(self, thread_id: str, user_message: str, assistant_message: str) -> None:
        document = self.load_document()
        threads = document["threads"]
        target: dict[str, Any] | None = None
        for item in threads:
            if isinstance(item, dict) and item.get("id") == thread_id:
                target = item
                break
        if target is None:
            target = {
                "id": thread_id,
                "title": "新对话",
                "updatedAt": datetime.now(UTC).isoformat(),
                "messages": [],
            }
            threads.insert(0, target)
        messages = target.get("messages")
        if not isinstance(messages, list):
            messages = []
        messages.append({"role": "user", "text": user_message.strip()})
        messages.append({"role": "assistant", "text": assistant_message.strip()})
        target["messages"] = messages[-MAX_THREAD_MESSAGES:]
        target["updatedAt"] = datetime.now(UTC).isoformat()
        if target.get("title") in {"", "新对话", "New chat"} and user_message.strip():
            target["title"] = user_message.strip()[:48]
        self.save_document(current_id=thread_id, threads=threads)
