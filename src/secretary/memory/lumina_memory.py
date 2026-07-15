"""Lumina three-layer memory system.

Layer 1: MEMORY.md + USER.md (durable facts, frozen snapshot in system prompt)
Layer 2: Session archive (all conversations in SQLite with FTS5)
Layer 3: Episodic memory (task execution records with success/failure)
"""

from __future__ import annotations

import json
import re as _re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

MEMORY_MD_MAX_CHARS = 2200
USER_MD_MAX_CHARS = 1375


class LuminaMemory:
    def __init__(self, data_dir: Path, session_db: Path | None = None) -> None:
        self._data_dir = data_dir
        self._memories_dir = data_dir / "memories"
        self._memories_dir.mkdir(parents=True, exist_ok=True)
        self._session_db = session_db or data_dir / "sessions.db"
        self._session_db.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_session_schema()

    @property
    def memory_md_path(self) -> Path:
        return self._memories_dir / "MEMORY.md"

    @property
    def user_md_path(self) -> Path:
        return self._memories_dir / "USER.md"

    def read_memory_md(self) -> str:
        path = self.memory_md_path
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def write_memory_md(self, content: str) -> None:
        content = content.strip()
        if len(content) > MEMORY_MD_MAX_CHARS:
            content = content[:MEMORY_MD_MAX_CHARS]
        self.memory_md_path.write_text(content + "\n", encoding="utf-8")

    def append_memory_md(self, line: str) -> None:
        existing = self.read_memory_md()
        if line.strip() in existing:
            return
        updated = f"{existing}\n{line.strip()}".strip()
        if len(updated) > MEMORY_MD_MAX_CHARS:
            updated = updated[:MEMORY_MD_MAX_CHARS]
        self.write_memory_md(updated)

    def mutate_memory(
        self,
        action: str,
        target: str,
        *,
        text: str = "",
        old_text: str = "",
    ) -> str:
        """Apply add/replace/remove to MEMORY.md or USER.md."""
        normalized_action = action.strip().lower()
        normalized_target = target.strip().lower()
        if normalized_action not in {"add", "replace", "remove"}:
            raise ValueError(f"unknown memory action: {action}")
        if normalized_target not in {"memory", "user"}:
            raise ValueError(f"unknown memory target: {target}")

        read_fn = self.read_memory_md if normalized_target == "memory" else self.read_user_md
        write_fn = self.write_memory_md if normalized_target == "memory" else self.write_user_md
        label = "MEMORY.md" if normalized_target == "memory" else "USER.md"
        content = read_fn()

        if normalized_action == "add":
            line = text.strip()
            if not line:
                return f"Error: empty text for add to {label}"
            if line in content:
                return f"Already present in {label}"
            if content:
                updated = f"{content}\n{line}".strip()
            else:
                updated = line
            write_fn(updated)
            return f"Added to {label}"

        if normalized_action == "replace":
            needle = old_text.strip()
            replacement = text.strip()
            if not needle:
                return f"Error: old_text required for replace in {label}"
            if needle not in content:
                return f"Error: old_text not found in {label}"
            write_fn(content.replace(needle, replacement, 1))
            return f"Replaced in {label}"

        needle = old_text.strip()
        if not needle:
            return f"Error: old_text required for remove from {label}"
        if needle not in content:
            return f"Error: old_text not found in {label}"
        updated = content.replace(needle, "", 1)
        while "\n\n\n" in updated:
            updated = updated.replace("\n\n\n", "\n\n")
        write_fn(updated.strip())
        return f"Removed from {label}"

    def read_user_md(self) -> str:
        path = self.user_md_path
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def write_user_md(self, content: str) -> None:
        content = content.strip()
        if len(content) > USER_MD_MAX_CHARS:
            content = content[:USER_MD_MAX_CHARS]
        self.user_md_path.write_text(content + "\n", encoding="utf-8")

    def import_from_hermes(self) -> dict[str, str]:
        """One-shot import of MEMORY.md and USER.md from ~/.hermes/ into Lumina.

        Looks for files at both top-level and `memories/` nested paths.
        First existing file per target wins; overwrites Lumina's copy.
        Returns dict mapping target key ("memory_md" / "user_md") to imported path.
        """
        hermes_root = Path.home() / ".hermes"
        candidates: list[tuple[Path, Path, str]] = [
            (hermes_root / "MEMORY.md", self.memory_md_path, "memory_md"),
            (hermes_root / "memories" / "MEMORY.md", self.memory_md_path, "memory_md"),
            (hermes_root / "USER.md", self.user_md_path, "user_md"),
            (hermes_root / "memories" / "USER.md", self.user_md_path, "user_md"),
        ]
        imported: dict[str, str] = {}
        for src, dst, key in candidates:
            if key in imported:
                continue
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8").strip()
            if not text:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text + "\n", encoding="utf-8")
            imported[key] = str(src)
        return imported

    def prompt_snapshot(self) -> str:
        memory = self.read_memory_md()
        user = self.read_user_md()
        parts = []
        if memory:
            parts.append(f"## Durable Memory\n{memory}")
        if user:
            parts.append(f"## User Profile\n{user}")
        return "\n\n".join(parts) if parts else ""

    def _connect_session(self) -> sqlite3.Connection:
        conn = getattr(self._local, "session_conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn  # type: ignore[no-any-return]
            except sqlite3.Error:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
        conn = sqlite3.connect(self._session_db)
        conn.row_factory = sqlite3.Row
        self._local.session_conn = conn
        return conn

    def _init_session_schema(self) -> None:
        with self._connect_session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    summary TEXT
                );

                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts USING fts5(
                    session_id UNINDEXED,
                    role UNINDEXED,
                    content,
                    content='session_messages',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS sm_ai AFTER INSERT ON session_messages BEGIN
                    INSERT INTO session_messages_fts(rowid, session_id, role, content)
                    VALUES (new.rowid, new.session_id, new.role, new.content);
                END;

                CREATE TRIGGER IF NOT EXISTS sm_ad AFTER DELETE ON session_messages BEGIN
                    INSERT INTO session_messages_fts(session_messages_fts, rowid, session_id, role, content)
                    VALUES ('delete', old.rowid, old.session_id, old.role, old.content);
                END;

                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    result TEXT,
                    success INTEGER NOT NULL DEFAULT 0,
                    tools_used TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    failure_mode TEXT,
                    reflection_text TEXT,
                    thread_id TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                    episode_id UNINDEXED,
                    task,
                    result,
                    failure_mode UNINDEXED,
                    reflection_text,
                    content='episodes',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS ep_ai AFTER INSERT ON episodes BEGIN
                    INSERT INTO episodes_fts(rowid, episode_id, task, result, failure_mode, reflection_text)
                    VALUES (new.rowid, new.episode_id, new.task, new.result, new.failure_mode, new.reflection_text);
                END;

                CREATE TRIGGER IF NOT EXISTS ep_ad AFTER DELETE ON episodes BEGIN
                    INSERT INTO episodes_fts(episodes_fts, rowid, episode_id, task, result, failure_mode, reflection_text)
                    VALUES ('delete', old.rowid, old.episode_id, old.task, old.result, old.failure_mode, old.reflection_text);
                END;
                """
            )
            self._migrate_episodes_schema()

    def _migrate_episodes_schema(self) -> None:
        """Add F21 columns to existing episodes table (idempotent)."""
        new_columns = ["failure_mode", "reflection_text", "thread_id"]
        with self._connect_session() as conn:
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(episodes)")}
            for col in new_columns:
                if col not in existing:
                    conn.execute(f"ALTER TABLE episodes ADD COLUMN {col} TEXT")

    def create_session(self, session_id: str) -> None:
        with self._connect_session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
                (session_id, datetime.now(UTC).isoformat()),
            )

    def end_session(self, session_id: str, summary: str = "") -> None:
        with self._connect_session() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ?, summary = ? WHERE session_id = ?",
                (datetime.now(UTC).isoformat(), summary, session_id),
            )

    def add_message(self, session_id: str, role: str, content: str) -> None:
        with self._connect_session() as conn:
            conn.execute(
                "INSERT INTO session_messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role, content[:MAX_MESSAGE_LEN], datetime.now(UTC).isoformat()),
            )

    def search_sessions(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        safe_query = _sanitize_fts(query)
        with self._connect_session() as conn:
            rows = conn.execute(
                """
                SELECT m.session_id, m.role, m.content, m.timestamp
                FROM session_messages_fts f
                JOIN session_messages m ON m.rowid = f.rowid
                WHERE session_messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, limit),
            ).fetchall()
        if not rows:
            pattern = f"%{query}%"
            with self._connect_session() as conn:
                rows = conn.execute(
                    """
                    SELECT session_id, role, content, timestamp
                    FROM session_messages
                    WHERE content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (pattern, limit),
                ).fetchall()
        return [
            {
                "session_id": str(r["session_id"]),
                "role": str(r["role"]),
                "content": str(r["content"])[:500],
                "timestamp": str(r["timestamp"]),
            }
            for r in rows
        ]

    def recent_session_messages(self, limit: int = 40) -> list[dict[str, str]]:
        with self._connect_session() as conn:
            rows = conn.execute(
                """
                SELECT session_id, role, content, timestamp
                FROM session_messages
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (max(limit, 1),),
            ).fetchall()
        items = [
            {
                "session_id": str(r["session_id"]),
                "role": str(r["role"]),
                "content": str(r["content"]),
                "timestamp": str(r["timestamp"]),
            }
            for r in rows
        ]
        items.reverse()
        return items

    def save_episode(
        self,
        episode_id: str,
        task: str,
        steps: list[dict[str, str]],
        result: str,
        success: bool,
        tools_used: list[str],
    ) -> None:
        with self._connect_session() as conn:
            conn.execute(
                """
                INSERT INTO episodes (episode_id, task, steps_json, result, success, tools_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    steps_json=excluded.steps_json,
                    result=excluded.result,
                    success=excluded.success,
                    tools_used=excluded.tools_used
                """,
                (
                    episode_id,
                    task[:500],
                    json.dumps(steps, ensure_ascii=False),
                    result[:2000],
                    1 if success else 0,
                    json.dumps(tools_used, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def search_episodes(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        safe_query = _sanitize_fts(query)
        with self._connect_session() as conn:
            rows = conn.execute(
                """
                SELECT e.episode_id, e.task, e.result, e.success, e.tools_used, e.created_at
                FROM episodes_fts f
                JOIN episodes e ON e.rowid = f.rowid
                WHERE episodes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, limit),
            ).fetchall()
        if not rows:
            pattern = f"%{query}%"
            with self._connect_session() as conn:
                rows = conn.execute(
                    """
                    SELECT episode_id, task, result, success, tools_used, created_at
                    FROM episodes
                    WHERE task LIKE ? OR result LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
        items: list[dict[str, object]] = [
            {
                "episode_id": str(r["episode_id"]),
                "task": str(r["task"]),
                "result": str(r["result"])[:500],
                "success": bool(r["success"]),
                "tools_used": str(r["tools_used"]),
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]
        return items


MAX_MESSAGE_LEN = 4000

_FTS_SPECIAL = _re.compile(r'[*"()|:]')


def _sanitize_fts(query: str) -> str:
    cleaned = _FTS_SPECIAL.sub("", query).strip()
    if not cleaned:
        return query
    tokens = cleaned.split()
    return " OR ".join(tokens)
