"""Playwright E2E smoke for conversation tree branching (Task 7.1 & 10.4).

The frontend renders thread state from the server response (``applyThreadPayload``
replaces local state wholesale), so the branching/rollback UI can be exercised
deterministically with an in-browser mock chat backend installed via
``page.route``. The mock faithfully implements the ``/api/chat*`` contract
(`append_turn` with ``parent_message_id`` forking, ``rollback`` archiving
descendants, ``restore`` un-archiving, active-leaf switching, tree view) —
mirroring ``secretary.services.chat_threads`` semantics — so no real LLM and
no real backend chat logic are required.

The live backend from ``conftest.live_base_url`` is still started: it only
serves the static UI shell (HTML/JS/CSS). Every ``/api/chat*`` request is
intercepted by the mock; other routes (``/api/health``, static assets) fall
through to the real backend.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, Route  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _chat_reply(reply: str) -> dict[str, object]:
    """Canned /api/chat response (no confirmation, grounded, no tools)."""
    return {
        "reply": reply,
        "profile_excerpt": "",
        "used_tools": [],
        "total_steps": 1,
        "route": "",
        "needs_confirmation": False,
        "confirmation_description": "",
        "confirmation_action_id": "",
        "confirmation_risk_level": "",
        "confirmation_kind": "",
        "allow_permanent_read": False,
        "allow_session_write": False,
        "grounding_verified": True,
        "grounding_note": "",
        "files_read": [],
        "usage_prompt_tokens": 1,
        "usage_completion_tokens": 2,
        "usage_total_tokens": 3,
    }


class _MockChatBackend:
    """In-memory implementation of the /api/chat* thread/tree contract.

    Mirrors ``secretary.services.chat_threads`` so the frontend tree UI is
    exercised against the same semantics the real backend exposes. Assistant
    nodes use role ``"bot"`` (the frontend's native role value, which
    ``appendMessageInternal`` maps directly to the ``message bot`` class).
    """

    def __init__(self) -> None:
        self.threads: list[dict[str, object]] = []
        self.current_id: str = ""

    # --- helpers ---
    @staticmethod
    def _msg_id() -> str:
        return "m_" + uuid.uuid4().hex[:8]

    @staticmethod
    def _thread_id() -> str:
        return "t_" + uuid.uuid4().hex[:10]

    def _payload(self) -> dict[str, object]:
        return {"current_id": self.current_id, "threads": self.threads}

    def _find(self, thread_id: str) -> dict[str, object] | None:
        for t in self.threads:
            if t.get("id") == thread_id:
                return t
        return None

    @staticmethod
    def _descendants(thread: dict[str, object], root_id: str) -> list[str]:
        children: dict[str, list[dict[str, object]]] = {}
        for m in thread.get("messages", []):  # type: ignore[union-attr]
            children.setdefault(m.get("parent_id", "") or "", []).append(m)  # type: ignore[union-attr]
        out: list[str] = []
        stack = list(children.get(root_id, []))
        seen: set[str] = set()
        while stack:
            m = stack.pop()
            mid = m.get("id")  # type: ignore[union-attr]
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(mid)
            stack.extend(children.get(mid, []))
        return out

    def _active_path_ids(self, thread: dict[str, object]) -> list[str]:
        by_id: dict[str, dict[str, object]] = {}
        for m in thread.get("messages", []):  # type: ignore[union-attr]
            if m.get("id"):
                by_id[m["id"]] = m  # type: ignore[index]
        leaf = thread.get("active_leaf_id", "") or ""
        out: list[str] = []
        seen: set[str] = set()
        cur: str = leaf
        guard = 0
        while cur and cur in by_id and cur not in seen and guard < 1000:
            seen.add(cur)
            out.append(cur)
            cur = by_id[cur].get("parent_id", "") or ""  # type: ignore[union-attr]
            guard += 1
        return out

    # --- thread CRUD (return {current_id, threads}) ---
    def list_threads(self) -> dict[str, object]:
        return self._payload()

    def create_thread(self, title: str = "新对话") -> dict[str, object]:
        tid = self._thread_id()
        thread: dict[str, object] = {
            "id": tid,
            "title": title or "新对话",
            "updatedAt": _now(),
            "messages": [],
            "active_leaf_id": "",
        }
        self.threads.insert(0, thread)
        self.current_id = tid
        return self._payload()

    def set_current(self, thread_id: str) -> dict[str, object]:
        if any(t.get("id") == thread_id for t in self.threads):
            self.current_id = thread_id
        return self._payload()

    def delete_thread(self, thread_id: str) -> dict[str, object]:
        self.threads = [t for t in self.threads if t.get("id") != thread_id]
        if self.current_id == thread_id:
            self.current_id = self.threads[0]["id"] if self.threads else ""
        return self._payload()

    def replace_all(self, current_id: str, threads: list[dict[str, object]]) -> dict[str, object]:
        # Faithfully accept client-pushed state. Only invoked if sync fails,
        # which never happens here (mock sync always succeeds) — so this never
        # clobbers the mock's authoritative state in practice.
        self.threads = threads
        self.current_id = current_id
        return self._payload()

    # --- tree mutation (return {current_id, threads}) ---
    def append_turn(
        self,
        thread_id: str,
        user_message: str,
        assistant_message: str,
        parent_message_id: str = "",
    ) -> dict[str, object]:
        target = self._find(thread_id)
        if target is None:
            target = {
                "id": thread_id,
                "title": "新对话",
                "updatedAt": _now(),
                "messages": [],
                "active_leaf_id": "",
            }
            self.threads.insert(0, target)
        messages = target.setdefault("messages", [])  # type: ignore[union-attr]
        parent_id = parent_message_id or (target.get("active_leaf_id") or "")
        user_node: dict[str, object] = {
            "id": self._msg_id(),
            "parent_id": parent_id,
            "role": "user",
            "text": user_message.strip(),
            "archived": False,
        }
        assistant_node: dict[str, object] = {
            "id": self._msg_id(),
            "parent_id": user_node["id"],
            "role": "bot",
            "text": assistant_message.strip(),
            "archived": False,
        }
        messages.append(user_node)  # type: ignore[union-attr]
        messages.append(assistant_node)  # type: ignore[union-attr]
        target["active_leaf_id"] = assistant_node["id"]
        target["updatedAt"] = _now()
        if user_message.strip() and (
            not str(target.get("title") or "").strip()
            or str(target.get("title") or "").strip() == "新对话"
        ):
            target["title"] = user_message.strip()[:48]
        return self._payload()

    def set_active_leaf(self, thread_id: str, leaf_id: str) -> dict[str, object]:
        target = self._find(thread_id)
        if target:
            ids = {m.get("id") for m in target.get("messages", [])}  # type: ignore[union-attr]
            if leaf_id in ids:
                target["active_leaf_id"] = leaf_id
        return self._payload()

    def rollback(self, thread_id: str, to_message_id: str) -> dict[str, object]:
        target = self._find(thread_id)
        if target:
            messages = target.get("messages", [])  # type: ignore[union-attr]
            if any(m.get("id") == to_message_id for m in messages):
                desc = set(self._descendants(target, to_message_id))
                for m in messages:
                    mid = m.get("id")
                    if mid == to_message_id:
                        m["archived"] = False  # type: ignore[index]
                    elif mid in desc:
                        m["archived"] = True  # type: ignore[index]
                target["active_leaf_id"] = to_message_id
        return self._payload()

    def restore(self, thread_id: str, message_id: str) -> dict[str, object]:
        target = self._find(thread_id)
        if target:
            messages = target.get("messages", [])  # type: ignore[union-attr]
            if any(m.get("id") == message_id for m in messages):
                restore_ids = {message_id} | set(self._descendants(target, message_id))
                for m in messages:
                    if m.get("id") in restore_ids:
                        m["archived"] = False  # type: ignore[index]
        return self._payload()

    def tree_view(self, thread_id: str) -> dict[str, object]:
        target = self._find(thread_id)
        if not target:
            return {"nodes": [], "root_id": "", "active_leaf_id": ""}
        messages = target.get("messages", [])  # type: ignore[union-attr]
        active_ids = set(self._active_path_ids(target))
        by_id = {m["id"]: m for m in messages if m.get("id")}  # type: ignore[index]
        # user_id -> assistant/bot child (parent_id == user_id)
        assistant_of_user: dict[str, dict[str, object]] = {}
        for m in messages:
            if m.get("role") not in ("assistant", "bot"):  # type: ignore[union-attr]
                continue
            pid = m.get("parent_id", "") or ""  # type: ignore[union-attr]
            if pid and pid in by_id and by_id[pid].get("role") == "user":
                assistant_of_user[pid] = m
        msg_to_turn: dict[str, str] = {}
        for m in messages:
            if m.get("role") != "user":  # type: ignore[union-attr]
                continue
            mid = m.get("id")  # type: ignore[union-attr]
            if not mid:
                continue
            assistant = assistant_of_user.get(mid)
            turn_id = assistant["id"] if assistant else mid
            msg_to_turn[mid] = turn_id
            if assistant:
                msg_to_turn[assistant["id"]] = turn_id
        nodes: list[dict[str, object]] = []
        root_id = ""
        for m in messages:
            if m.get("role") != "user":  # type: ignore[union-attr]
                continue
            mid = m.get("id")  # type: ignore[union-attr]
            if not mid:
                continue
            assistant = assistant_of_user.get(mid)
            turn_id = msg_to_turn.get(mid, mid)
            raw_parent = m.get("parent_id", "") or ""  # type: ignore[union-attr]
            parent_id = msg_to_turn.get(raw_parent, "") if raw_parent else ""
            if not parent_id and not root_id:
                root_id = turn_id
            user_text = m.get("text") or ""  # type: ignore[union-attr]
            assistant_text = (assistant.get("text") or "") if assistant else ""  # type: ignore[union-attr]
            nodes.append(
                {
                    "id": turn_id,
                    "parent_id": parent_id,
                    "user_preview": user_text[:80],
                    "assistant_preview": assistant_text[:80],
                    "has_assistant": assistant is not None,
                    "archived": bool(m.get("archived", False))  # type: ignore[union-attr]
                    or (bool(assistant.get("archived", False)) if assistant else False),
                    "active": turn_id in active_ids,
                }
            )
        return {
            "nodes": nodes,
            "root_id": root_id,
            "active_leaf_id": target.get("active_leaf_id", ""),
        }


def _fulfill_json(route: Route, payload: object) -> None:
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


def _install_mock_backend(page: Page, backend: _MockChatBackend) -> None:
    """Intercept every /api/chat* request and route it to the in-memory backend."""

    def handler(route: Route) -> None:
        request = route.request
        method = request.method
        url = request.url.split("?", 1)[0]
        idx = url.find("/api/chat")
        rel = url[idx:] if idx >= 0 else ""

        # SSE progress stream — short-circuit with an empty 200 so the
        # fire-and-forget subscriber resolves immediately.
        if rel.startswith("/api/chat/progress/"):
            route.fulfill(status=200, content_type="text/event-stream", body="")
            return

        raw = request.post_data
        try:
            body = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            body = None

        # POST /api/chat — mocked LLM reply + append_turn (fork-aware).
        if rel == "/api/chat" and method == "POST":
            msg = str((body or {}).get("message", ""))
            tid = str((body or {}).get("thread_id", ""))
            parent = str((body or {}).get("parent_message_id", "") or "")
            reply = f"这是对「{msg}」的回复。"
            backend.append_turn(tid, msg, reply, parent)
            _fulfill_json(route, _chat_reply(reply))
            return

        # /api/chat/threads (collection)
        if rel == "/api/chat/threads":
            if method == "GET":
                _fulfill_json(route, backend.list_threads())
                return
            if method == "POST":
                _fulfill_json(route, backend.create_thread(str((body or {}).get("title", "新对话"))))
                return
            if method == "PUT":
                _fulfill_json(
                    route,
                    backend.replace_all(
                        str((body or {}).get("current_id", "")),
                        (body or {}).get("threads", []) or [],
                    ),
                )
                return

        if rel == "/api/chat/threads/current" and method == "PUT":
            _fulfill_json(route, backend.set_current(str((body or {}).get("thread_id", ""))))
            return

        # /api/chat/threads/{tid} and /api/chat/threads/{tid}/{action}
        m = re.match(r"^/api/chat/threads/([^/]+)(?:/(.+))?$", rel)
        if m:
            tid = m.group(1)
            rest = m.group(2)
            if rest is None and method == "DELETE":
                _fulfill_json(route, backend.delete_thread(tid))
                return
            if rest == "active-leaf" and method == "PUT":
                _fulfill_json(route, backend.set_active_leaf(tid, str((body or {}).get("leaf_id", ""))))
                return
            if rest == "tree" and method == "GET":
                _fulfill_json(route, backend.tree_view(tid))
                return
            if rest == "rollback" and method == "POST":
                _fulfill_json(route, backend.rollback(tid, str((body or {}).get("to_message_id", ""))))
                return
            if rest == "restore" and method == "POST":
                _fulfill_json(route, backend.restore(tid, str((body or {}).get("message_id", ""))))
                return

        # Anything else under /api/chat* — pass through to the real backend.
        route.continue_()

    page.route(re.compile(r".*/api/chat(?:/.*)?$"), handler)


@pytest.fixture
def chat_page(page: Page, live_base_url: str) -> tuple[Page, _MockChatBackend]:
    """A page with the mock chat backend installed and the UI loaded.

    Pre-seeds one empty thread so ``initThreads`` finds a current thread
    immediately (no create-on-load race). Returns ``(page, backend)`` so tests
    can read authoritative message ids/timestamps from the mock state.
    """
    backend = _MockChatBackend()
    backend.create_thread("新对话")
    _install_mock_backend(page, backend)
    page.goto("/")
    page.wait_for_selector("#chat-input", timeout=15_000)
    page.wait_for_selector(".thread-item", timeout=15_000)
    return page, backend


# --- interaction helpers ---


def _send(page: Page, text: str) -> None:
    page.locator("#chat-input").fill(text)
    page.locator("#btn-send").click()


def _wait_turn(page: Page, backend: _MockChatBackend, expected_substring: str) -> None:
    """Wait for the mocked assistant reply to be rendered.

    With ``render: false`` sync, the DOM keeps locally-generated message ids
    that differ from the mock backend's ids. Waiting on the bot message text
    is more robust than matching ``data-msg-id``.
    """
    from playwright.sync_api import expect as _expect

    bot = page.locator("#messages .message.bot").last
    _expect(bot).to_be_visible(timeout=15_000)
    _expect(bot).to_contain_text(expected_substring, timeout=5_000)


def expect_locator_text(locator, substring: str) -> None:
    # Thin wrapper kept local to avoid importing expect at module import time
    # when playwright is absent (importorskip already guards the module, but
    # this keeps call sites terse).
    from playwright.sync_api import expect as _expect

    _expect(locator).to_contain_text(substring)


def _click_action(page: Page, msg_id: str, action: str) -> None:
    """Hover a message row (reveals .msg-actions) then click an action button."""
    row = page.locator(f'#messages .message[data-msg-id="{msg_id}"]')
    row.hover()
    row.locator(f'button[data-action="{action}"]').click()


# --- Task 7.1: fork smoke ---


def test_branch_fork_and_sibling_switch(chat_page: tuple[Page, _MockChatBackend]) -> None:
    page, backend = chat_page

    # 3. Two turns -> active path: user1 -> bot1 -> user2 -> bot2 (4 msgs).
    _send(page, "第一条")
    _wait_turn(page, backend, "第一条")
    _send(page, "第二条")
    _wait_turn(page, backend, "第二条")
    page.locator("#messages .message").nth(0).wait_for(state="visible", timeout=10_000)
    from playwright.sync_api import expect

    expect(page.locator("#messages .message")).to_have_count(4)

    # 4. Fork from bot1 (2nd message). bot1 already has a child (user2), so the
    #    new turn becomes its second child -> siblings.
    bot1_id = backend.threads[0]["messages"][1]["id"]  # type: ignore[index]
    _click_action(page, bot1_id, "fork")

    # 5. Fork banner visible + composer enters fork-pending state.
    expect(page.locator("#fork-banner")).to_be_visible(timeout=5_000)
    expect(page.locator("#chat-input.fork-pending")).to_be_visible()

    # 6. Send the forked message (carries parent_message_id=bot1).
    _send(page, "分叉回复")

    # 7. New branch renders; old messages preserved. Active path is still 4
    #    messages: user1, bot1, user3(fork), bot3(fork).
    _wait_turn(page, backend, "分叉回复")
    expect(page.locator("#messages .message")).to_have_count(4)

    # 8. Sibling switcher appears on the forked user message (bot1 now has two
    #    children: user2 and user3). New branch is the 2nd sibling -> "2/2".
    expect(page.locator(".sibling-switcher")).to_have_count(1)
    expect(page.locator(".sibling-switcher .sibling-count")).to_have_text("2/2")
    expect(page.locator("#messages .message").nth(2).locator(".bubble")).to_contain_text(
        "分叉回复"
    )

    # 9. Switch siblings. At "2/2" the prev (‹) button is enabled; clicking it
    #    jumps to the original branch (user2 -> bot2), count becomes "1/2".
    _click_sibling(page, "prev")
    expect(page.locator(".sibling-switcher .sibling-count")).to_have_text("1/2")
    expect(page.locator("#messages .message").nth(2).locator(".bubble")).to_contain_text(
        "第二条"
    )

    # Now next (›) is enabled — click it to switch back to the fork branch.
    _click_sibling(page, "next")
    expect(page.locator(".sibling-switcher .sibling-count")).to_have_text("2/2")
    expect(page.locator("#messages .message").nth(2).locator(".bubble")).to_contain_text(
        "分叉回复"
    )


def _click_sibling(page: Page, direction: str) -> None:
    # The switcher lives on the active-path message at the fork point's child
    # level (index 2 of the 4-message path). Hover first to reveal .msg-actions.
    row = page.locator("#messages .message").nth(2)
    row.hover()
    row.locator(f'button[data-action="sibling-{direction}"]').click()


# --- Task 10.4: rollback smoke ---


def test_rollback_archive_and_restore(chat_page: tuple[Page, _MockChatBackend]) -> None:
    page, backend = chat_page
    from playwright.sync_api import expect

    # 1. Build 4 messages: user1, bot1, user2, bot2.
    _send(page, "第一条")
    _wait_turn(page, backend, "第一条")
    _send(page, "第二条")
    _wait_turn(page, backend, "第二条")
    expect(page.locator("#messages .message")).to_have_count(4)

    # 2. Roll back to bot1 (2nd message). The frontend uses window.confirm(),
    #    so accept the dialog before the click dispatches.
    bot1_id = backend.threads[0]["messages"][1]["id"]  # type: ignore[index]
    page.once("dialog", lambda dialog: dialog.accept())
    _click_action(page, bot1_id, "rollback")

    # 4. Descendants (user2, bot2) leave the DOM; active path = user1, bot1.
    expect(page.locator("#messages .message")).to_have_count(2)
    expect(page.locator("#messages .message.archived")).to_have_count(0)

    # 5. Turn on "show archived".
    page.locator("#show-archived-toggle").check()

    # 6. Archived messages reappear, greyed (user2 + bot2).
    expect(page.locator("#messages .message")).to_have_count(4)
    expect(page.locator("#messages .message.archived")).to_have_count(2)

    # 7. Restore the first archived message (user2). Restore un-archives the
    #    node and its descendants (bot2) but does NOT move active_leaf, so the
    #    now non-archived off-path messages leave the "archived" view.
    archived_row = page.locator("#messages .message.archived").first
    archived_row.hover()
    archived_row.locator('button[data-action="restore"]').click()

    # 8. Archived flag cleared — no greyed messages remain; active path intact.
    expect(page.locator("#messages .message.archived")).to_have_count(0)
    expect(page.locator("#messages .message")).to_have_count(2)
    expect(page.locator("#messages .message").nth(0).locator(".bubble")).to_contain_text(
        "第一条"
    )
