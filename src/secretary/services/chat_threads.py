"""Persistent chat threads (multi-session UI + agent history per thread).

Messages are modeled as tree nodes: each carries a stable ``id``
(``m_<uuid8>``), a ``parent_id`` (root is ``""``), and an ``archived`` flag.
The thread records the currently displayed path via ``active_leaf_id``;
``active_path`` walks from that leaf back to the root.
"""

from __future__ import annotations

import json
import threading
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


def _new_message_id() -> str:
    return f"m_{uuid.uuid4().hex[:8]}"


def _migrate_thread(thread: dict[str, Any]) -> bool:
    """Backfill id/parent_id/archived on messages and active_leaf_id on thread.

    Returns True if any field was backfilled so the caller can persist.
    """
    changed = False
    messages = thread.get("messages")
    if not isinstance(messages, list):
        messages = []
        thread["messages"] = messages
        changed = True
    prev_id = ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        mid = msg.get("id")
        if not isinstance(mid, str) or not mid:
            mid = _new_message_id()
            msg["id"] = mid
            changed = True
        parent_id = msg.get("parent_id")
        if not isinstance(parent_id, str):
            msg["parent_id"] = prev_id
            changed = True
        archived = msg.get("archived")
        if not isinstance(archived, bool):
            msg["archived"] = False
            changed = True
        prev_id = mid
    active_leaf_id = thread.get("active_leaf_id")
    if not isinstance(active_leaf_id, str):
        last_id = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and isinstance(msg.get("id"), str) and msg["id"]:
                last_id = msg["id"]
                break
        thread["active_leaf_id"] = last_id
        changed = True
    return changed


def _message_id_set(thread: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    messages = thread.get("messages")
    if not isinstance(messages, list):
        return ids
    for msg in messages:
        if isinstance(msg, dict) and isinstance(msg.get("id"), str) and msg["id"]:
            ids.add(msg["id"])
    return ids


def _structural_path(thread: dict[str, Any]) -> list[dict[str, Any]]:
    """Root→active_leaf path, including archived nodes (cycle-safe)."""
    messages = thread.get("messages")
    if not isinstance(messages, list):
        return []
    by_id: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if isinstance(msg, dict) and isinstance(msg.get("id"), str) and msg["id"]:
            by_id[msg["id"]] = msg
    leaf_id = thread.get("active_leaf_id")
    if not isinstance(leaf_id, str) or not leaf_id or leaf_id not in by_id:
        return []
    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = leaf_id
    while current and current in by_id and current not in seen:
        node = by_id[current]
        path.append(node)
        seen.add(current)
        parent = node.get("parent_id")
        current = parent if isinstance(parent, str) else ""
    path.reverse()
    return path


def _active_path(thread: dict[str, Any]) -> list[dict[str, Any]]:
    """Root→active_leaf path with archived nodes filtered out."""
    return [m for m in _structural_path(thread) if not m.get("archived")]


def _descendant_ids(thread: dict[str, Any], root_id: str) -> list[str]:
    """All descendant ids of ``root_id`` (excluding itself), via parent_id links."""
    messages = thread.get("messages")
    if not isinstance(messages, list):
        return []
    children: dict[str, list[str]] = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        parent = msg.get("parent_id")
        mid = msg.get("id")
        if isinstance(parent, str) and parent and isinstance(mid, str) and mid:
            children.setdefault(parent, []).append(mid)
    result: list[str] = []
    stack = list(children.get(root_id, []))
    while stack:
        cid = stack.pop()
        result.append(cid)
        stack.extend(children.get(cid, []))
    return result


class ChatThreadStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def load_document(self) -> dict[str, Any]:
        with self._lock:
            return self._load_document_locked()

    def _load_document_locked(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"current_id": "", "threads": []}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"current_id": "", "threads": []}
        threads = payload.get("threads")
        if not isinstance(threads, list):
            threads = []
        threads = [item for item in threads if isinstance(item, dict)]
        migrated = False
        for thread in threads:
            if _migrate_thread(thread):
                migrated = True
        current_id = str(payload.get("current_id") or "")
        if migrated:
            self._save_document_locked(current_id=current_id, threads=threads)
        return {"current_id": current_id, "threads": threads}

    def save_document(self, *, current_id: str, threads: list[dict[str, Any]]) -> None:
        with self._lock:
            self._save_document_locked(current_id=current_id, threads=threads)

    def _save_document_locked(self, *, current_id: str, threads: list[dict[str, Any]]) -> None:
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
                "active_leaf_id": "",
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
            raw_messages = item.get("messages")
            if not isinstance(raw_messages, list):
                raw_messages = []
            normalized_messages: list[dict[str, Any]] = []
            prev_id = ""
            for message in raw_messages:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                text = message.get("text") or message.get("content")
                if role not in {"user", "assistant", "bot"} or not isinstance(text, str) or not text.strip():
                    continue
                normalized_role = "assistant" if role == "bot" else role
                mid = message.get("id")
                if not isinstance(mid, str) or not mid:
                    mid = _new_message_id()
                parent_id = message.get("parent_id")
                if not isinstance(parent_id, str) or not parent_id:
                    parent_id = prev_id
                archived = message.get("archived")
                if not isinstance(archived, bool):
                    archived = False
                node: dict[str, Any] = {
                    "id": mid,
                    "parent_id": parent_id,
                    "role": normalized_role,
                    "text": text.strip(),
                    "archived": archived,
                }
                ts = message.get("timestamp")
                if isinstance(ts, str) and ts:
                    node["timestamp"] = ts
                normalized_messages.append(node)
                prev_id = mid
            if len(normalized_messages) > MAX_THREAD_MESSAGES:
                normalized_messages = normalized_messages[-MAX_THREAD_MESSAGES:]
            retained_ids = {m["id"] for m in normalized_messages}
            active_leaf_id = item.get("active_leaf_id")
            if not isinstance(active_leaf_id, str) or active_leaf_id not in retained_ids:
                active_leaf_id = normalized_messages[-1]["id"] if normalized_messages else ""
            cleaned_item: dict[str, Any] = {
                "id": thread_id,
                "title": str(item.get("title") or "新对话")[:120],
                "updatedAt": str(item.get("updatedAt") or item.get("updated_at") or datetime.now(UTC).isoformat()),
                "messages": normalized_messages,
                "active_leaf_id": active_leaf_id,
            }
            auto_at = item.get("auto_title_at_turn")
            if isinstance(auto_at, int) and auto_at >= 0:
                cleaned_item["auto_title_at_turn"] = auto_at
            cleaned.append(cleaned_item)
        current = current_id if any(t["id"] == current_id for t in cleaned) else (cleaned[0]["id"] if cleaned else "")
        self.save_document(current_id=current, threads=cleaned)
        return self.list_view()

    def active_path(self, thread_id: str) -> list[dict[str, Any]]:
        document = self.load_document()
        for item in document["threads"]:
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            return _active_path(item)
        return []

    def agent_history(self, thread_id: str) -> list[dict[str, str]]:
        path = self.active_path(thread_id)
        history: list[dict[str, str]] = []
        for message in path[-MAX_HISTORY_MESSAGES:]:
            role = message.get("role")
            text = message.get("text") or message.get("content")
            if role in {"user", "assistant", "bot"} and isinstance(text, str) and text.strip():
                normalized = "assistant" if role == "bot" else str(role)
                history.append({"role": normalized, "content": text.strip()})
        return history

    def append_turn(
        self,
        thread_id: str,
        user_message: str,
        assistant_message: str,
        parent_message_id: str = "",
    ) -> None:
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
                "active_leaf_id": "",
            }
            threads.insert(0, target)
        messages = target.get("messages")
        if not isinstance(messages, list):
            messages = []
        parent_id = parent_message_id or (target.get("active_leaf_id") or "")
        now = datetime.now(UTC).isoformat()
        user_node: dict[str, Any] = {
            "id": _new_message_id(),
            "parent_id": parent_id,
            "role": "user",
            "text": user_message.strip(),
            "archived": False,
        }
        assistant_node: dict[str, Any] = {
            "id": _new_message_id(),
            "parent_id": user_node["id"],
            "role": "assistant",
            "text": assistant_message.strip(),
            "archived": False,
        }
        messages.append(user_node)
        messages.append(assistant_node)
        new_leaf_id = assistant_node["id"]
        if len(messages) > MAX_THREAD_MESSAGES:
            messages = messages[-MAX_THREAD_MESSAGES:]
            retained_ids = {m["id"] for m in messages if isinstance(m, dict) and m.get("id")}
            if new_leaf_id not in retained_ids:
                for m in reversed(messages):
                    if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]:
                        new_leaf_id = m["id"]
                        break
        target["messages"] = messages
        target["active_leaf_id"] = new_leaf_id
        target["updatedAt"] = now
        current_title = str(target.get("title") or "").strip()
        if user_message.strip() and (not current_title or current_title == "新对话"):
            from secretary.services.thread_title import heuristic_title

            target["title"] = heuristic_title(user_message)
        self.save_document(current_id=thread_id, threads=threads)

    def append_assistant_message(self, thread_id: str, assistant_message: str) -> bool:
        """Append a single assistant notice without inventing a fake user turn.

        Returns False when the thread does not exist (does not create one).
        """
        text = assistant_message.strip()
        if not thread_id or not text:
            return False
        document = self.load_document()
        threads = document["threads"]
        target: dict[str, Any] | None = None
        for item in threads:
            if isinstance(item, dict) and item.get("id") == thread_id:
                target = item
                break
        if target is None:
            return False
        messages = target.get("messages")
        if not isinstance(messages, list):
            messages = []
        parent_id = target.get("active_leaf_id") or ""
        assistant_node: dict[str, Any] = {
            "id": _new_message_id(),
            "parent_id": parent_id if isinstance(parent_id, str) else "",
            "role": "assistant",
            "text": text,
            "archived": False,
        }
        messages.append(assistant_node)
        if len(messages) > MAX_THREAD_MESSAGES:
            messages = messages[-MAX_THREAD_MESSAGES:]
        target["messages"] = messages
        target["active_leaf_id"] = assistant_node["id"]
        target["updatedAt"] = datetime.now(UTC).isoformat()
        self.save_document(current_id=document["current_id"], threads=threads)
        return True

    def maybe_refresh_title(
        self,
        thread_id: str,
        *,
        llm_config: Any | None = None,
    ) -> str | None:
        """Summarize and update the thread title when a refresh milestone is hit.

        Returns the new title when updated, otherwise None.
        """
        from secretary.services.thread_title import (
            should_refresh_title,
            summarize_thread_title,
            user_turn_count,
        )

        document = self.load_document()
        threads = document["threads"]
        target: dict[str, Any] | None = None
        for item in threads:
            if isinstance(item, dict) and item.get("id") == thread_id:
                target = item
                break
        if target is None:
            return None
        messages = target.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        turns = user_turn_count(messages)
        last = target.get("auto_title_at_turn")
        last_turn = int(last) if isinstance(last, int) else 0
        if not should_refresh_title(user_turns=turns, last_auto_title_turn=last_turn):
            return None
        fallback = str(target.get("title") or "新对话")
        title = summarize_thread_title(messages, llm_config, fallback=fallback)
        if not title:
            title = fallback
        target["title"] = title[:120]
        target["auto_title_at_turn"] = turns
        target["updatedAt"] = datetime.now(UTC).isoformat()
        self.save_document(current_id=document["current_id"], threads=threads)
        return title

    def set_active_leaf(self, thread_id: str, leaf_id: str) -> dict[str, Any]:
        document = self.load_document()
        threads = document["threads"]
        for item in threads:
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            if leaf_id in _message_id_set(item):
                item["active_leaf_id"] = leaf_id
                self.save_document(current_id=document["current_id"], threads=threads)
            break
        return self.list_view()

    def split_disconnected_chains(self, thread_id: str) -> dict[str, Any]:
        """检测线程内的断档(多个根节点),把断开的后续对话链拆分到新线程。

        当同一线程内出现多个 ``parent_id`` 为空的消息时,说明对话链断裂——
        通常是用户在同一线程内开始了全新话题。此方法保留第一条链(原始线程),
        把第 2 条及之后的每条独立链拆分到各自的新线程里,新线程标题取该链
        首条用户消息。
        """
        document = self.load_document()
        threads = document["threads"]
        target_idx = -1
        target: dict[str, Any] | None = None
        for i, item in enumerate(threads):
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            target = item
            target_idx = i
            break
        if target is None:
            return {"split_count": 0, "new_thread_ids": []}
        messages = target.get("messages")
        if not isinstance(messages, list) or not messages:
            return {"split_count": 0, "new_thread_ids": []}

        # 找出所有根消息(parent_id 为空或指向不存在的消息)
        msg_ids = {
            m["id"] for m in messages if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
        }
        root_user_msgs: list[dict[str, Any]] = []
        for m in messages:
            if not isinstance(m, dict) or m.get("role") != "user":
                continue
            pid = m.get("parent_id")
            if not isinstance(pid, str) or not pid or pid not in msg_ids:
                root_user_msgs.append(m)

        if len(root_user_msgs) <= 1:
            return {"split_count": 0, "new_thread_ids": []}

        # 第一条链保留在原线程;其余的拆分出去。
        # 为每条链收集所有后代消息(含根)。
        children_map: dict[str, list[str]] = {}
        for m in messages:
            if not isinstance(m, dict):
                continue
            pid = m.get("parent_id")
            mid = m.get("id")
            if isinstance(pid, str) and pid and isinstance(mid, str) and mid:
                children_map.setdefault(pid, []).append(mid)

        def collect_descendants(root_id: str) -> set[str]:
            result: set[str] = set()
            stack = [root_id]
            while stack:
                cid = stack.pop()
                if cid in result:
                    continue
                result.add(cid)
                stack.extend(children_map.get(cid, []))
            return result

        # 保留第一条链的消息 id 集合
        first_chain_ids = collect_descendants(root_user_msgs[0]["id"])
        # 原线程的 active_leaf_id 必须在第一条链里,否则选第一条链的最后一个消息
        current_leaf = target.get("active_leaf_id", "")
        if not isinstance(current_leaf, str) or current_leaf not in first_chain_ids:
            # 找第一条链的最后一个消息(按 messages 顺序)
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("id") in first_chain_ids:
                    current_leaf = m.get("id", "")
                    break

        new_threads: list[dict[str, Any]] = []
        new_thread_ids: list[str] = []
        for root_msg in root_user_msgs[1:]:
            chain_ids = collect_descendants(root_msg["id"])
            chain_messages = [
                m for m in messages if isinstance(m, dict) and m.get("id") in chain_ids
            ]
            if not chain_messages:
                continue
            # 新线程的 leaf:该链最后一条消息
            chain_leaf = chain_messages[-1].get("id", "")
            # 标题:首条用户消息
            title = (root_msg.get("text") or "新对话")[:48]
            new_thread_id = f"t_{uuid.uuid4().hex[:10]}"
            now = datetime.now(UTC).isoformat()
            new_thread = {
                "id": new_thread_id,
                "title": title,
                "updatedAt": now,
                "messages": chain_messages,
                "active_leaf_id": chain_leaf,
            }
            new_threads.append(new_thread)
            new_thread_ids.append(new_thread_id)

        # 从原线程移除被拆分的消息
        split_ids: set[str] = set()
        for nt in new_threads:
            for m in nt["messages"]:
                if isinstance(m, dict) and isinstance(m.get("id"), str):
                    split_ids.add(m["id"])
        retained_messages = [
            m for m in messages if not (isinstance(m, dict) and m.get("id") in split_ids)
        ]
        target["messages"] = retained_messages
        target["active_leaf_id"] = current_leaf
        # 在原线程后面插入新线程
        for j, nt in enumerate(new_threads):
            threads.insert(target_idx + 1 + j, nt)

        self.save_document(current_id=document["current_id"], threads=threads)
        return {"split_count": len(new_threads), "new_thread_ids": new_thread_ids}

    def thread_tree_view(self, thread_id: str) -> dict[str, Any]:
        """Return the conversation tree as *turn* nodes.

        A turn pairs a user message with its assistant reply (one round of
        Q&A). The turn id is the assistant message id when a reply exists,
        otherwise the user message id. ``parent_id`` is resolved through a
        message→turn map so the turn tree stays connected even when an older
        branch forked from a user message directly.
        """
        document = self.load_document()
        for item in document["threads"]:
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            messages = item.get("messages")
            if not isinstance(messages, list):
                messages = []
            active_ids = {
                m["id"]
                for m in _structural_path(item)
                if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]
            }
            by_id: dict[str, dict[str, Any]] = {}
            for msg in messages:
                if isinstance(msg, dict) and isinstance(msg.get("id"), str) and msg["id"]:
                    by_id[msg["id"]] = msg
            # user_id -> its assistant child (role=assistant, parent_id=user_id)
            assistant_of_user: dict[str, dict[str, Any]] = {}
            for msg in messages:
                if not isinstance(msg, dict) or msg.get("role") != "assistant":
                    continue
                pid = msg.get("parent_id")
                if (
                    isinstance(pid, str)
                    and pid
                    and pid in by_id
                    and by_id[pid].get("role") == "user"
                ):
                    assistant_of_user[pid] = msg
            # message_id -> turn_id, so a turn's parent_id always resolves to
            # the parent turn's representative id (keeps the turn tree linked).
            msg_to_turn: dict[str, str] = {}
            for msg in messages:
                if not isinstance(msg, dict) or msg.get("role") != "user":
                    continue
                mid = msg.get("id")
                if not isinstance(mid, str) or not mid:
                    continue
                assistant = assistant_of_user.get(mid)
                turn_id = assistant["id"] if assistant else mid
                msg_to_turn[mid] = turn_id
                if assistant:
                    msg_to_turn[assistant["id"]] = turn_id
            nodes: list[dict[str, Any]] = []
            root_id = ""
            for msg in messages:
                if not isinstance(msg, dict) or msg.get("role") != "user":
                    continue
                mid = msg.get("id")
                if not isinstance(mid, str) or not mid:
                    continue
                assistant = assistant_of_user.get(mid)
                turn_id = msg_to_turn.get(mid, mid)
                raw_parent = msg.get("parent_id")
                parent_id = (
                    msg_to_turn.get(raw_parent, "") if isinstance(raw_parent, str) else ""
                )
                if not parent_id and not root_id:
                    root_id = turn_id
                user_text = msg.get("text")
                user_preview = user_text[:80] if isinstance(user_text, str) else ""
                assistant_text = assistant.get("text") if assistant else ""
                assistant_preview = (
                    assistant_text[:80] if isinstance(assistant_text, str) else ""
                )
                archived = bool(msg.get("archived", False)) or (
                    bool(assistant.get("archived", False)) if assistant else False
                )
                nodes.append(
                    {
                        "id": turn_id,
                        "parent_id": parent_id,
                        "user_message_id": mid,
                        "assistant_message_id": assistant.get("id") if assistant else "",
                        "user_preview": user_preview,
                        "assistant_preview": assistant_preview,
                        "has_assistant": assistant is not None,
                        "archived": archived,
                        "active": turn_id in active_ids,
                    }
                )
            return {
                "nodes": nodes,
                "root_id": root_id,
                "active_leaf_id": str(item.get("active_leaf_id") or ""),
            }
        return {"nodes": [], "root_id": "", "active_leaf_id": ""}

    def rollback_to(self, thread_id: str, to_message_id: str) -> dict[str, Any]:
        document = self.load_document()
        threads = document["threads"]
        for item in threads:
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            messages = item.get("messages")
            if not isinstance(messages, list):
                break
            if not any(isinstance(m, dict) and m.get("id") == to_message_id for m in messages):
                break
            desc_ids = set(_descendant_ids(item, to_message_id))
            for m in messages:
                if not isinstance(m, dict):
                    continue
                mid = m.get("id")
                if mid == to_message_id:
                    m["archived"] = False
                elif mid in desc_ids:
                    m["archived"] = True
            item["active_leaf_id"] = to_message_id
            self.save_document(current_id=document["current_id"], threads=threads)
            break
        return self.list_view()

    def restore_archived(self, thread_id: str, message_id: str) -> dict[str, Any]:
        document = self.load_document()
        threads = document["threads"]
        for item in threads:
            if not isinstance(item, dict) or item.get("id") != thread_id:
                continue
            messages = item.get("messages")
            if not isinstance(messages, list):
                break
            if not any(isinstance(m, dict) and m.get("id") == message_id for m in messages):
                break
            restore_ids = {message_id} | set(_descendant_ids(item, message_id))
            for m in messages:
                if isinstance(m, dict) and m.get("id") in restore_ids:
                    m["archived"] = False
            self.save_document(current_id=document["current_id"], threads=threads)
            break
        return self.list_view()
