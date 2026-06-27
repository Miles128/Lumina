"""SQLite persistence for memory chunks and sync state."""

# ruff: noqa: E501

from __future__ import annotations

import json
import re as _re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from secretary.core.types import ConnectorHealth, ConnectorStatus, MemoryChunk, SourceKind
from secretary.exceptions import IngestError


class MemoryStore:
    """Local-first memory store with FTS search."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn  # type: ignore[no-any-return]
            except sqlite3.Error:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    title,
                    content,
                    content='memory_chunks',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS memory_chunks_ai AFTER INSERT ON memory_chunks BEGIN
                    INSERT INTO memory_chunks_fts(rowid, chunk_id, title, content)
                    VALUES (new.rowid, new.chunk_id, new.title, new.content);
                END;

                CREATE TRIGGER IF NOT EXISTS memory_chunks_ad AFTER DELETE ON memory_chunks BEGIN
                    INSERT INTO memory_chunks_fts(memory_chunks_fts, rowid, chunk_id, title, content)
                    VALUES ('delete', old.rowid, old.chunk_id, old.title, old.content);
                END;

                CREATE TRIGGER IF NOT EXISTS memory_chunks_au AFTER UPDATE ON memory_chunks BEGIN
                    INSERT INTO memory_chunks_fts(memory_chunks_fts, rowid, chunk_id, title, content)
                    VALUES ('delete', old.rowid, old.chunk_id, old.title, old.content);
                    INSERT INTO memory_chunks_fts(rowid, chunk_id, title, content)
                    VALUES (new.rowid, new.chunk_id, new.title, new.content);
                END;

                CREATE TABLE IF NOT EXISTS sync_state (
                    source TEXT PRIMARY KEY,
                    last_sync_at TEXT,
                    last_status TEXT NOT NULL,
                    last_message TEXT NOT NULL,
                    item_count INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def upsert_chunks(self, chunks: list[MemoryChunk]) -> int:
        if not chunks:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO memory_chunks (chunk_id, source, title, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    source=excluded.source,
                    title=excluded.title,
                    content=excluded.content,
                    metadata_json=excluded.metadata_json,
                    created_at=excluded.created_at
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.source.value,
                        chunk.title,
                        chunk.content,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                        chunk.created_at.isoformat(),
                    )
                    for chunk in chunks
                ],
            )
        return len(chunks)

    def purge_source(self, source: SourceKind) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_chunks WHERE source = ?",
                (source.value,),
            ).fetchone()
            count = int(row["count"]) if row else 0
            if count == 0:
                return 0
            conn.execute("DELETE FROM memory_chunks WHERE source = ?", (source.value,))
        return count

    def search(self, query: str, limit: int = 20) -> list[MemoryChunk]:
        safe_query = _sanitize_fts_query(query)
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT c.chunk_id, c.source, c.title, c.content, c.metadata_json, c.created_at
                    FROM memory_chunks_fts f
                    JOIN memory_chunks c ON c.rowid = f.rowid
                    WHERE memory_chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (safe_query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if rows:
            return [self._row_to_chunk(row) for row in rows]

        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, source, title, content, metadata_json, created_at
                FROM memory_chunks
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def list_by_source(self, source: SourceKind, limit: int = 100) -> list[MemoryChunk]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, source, title, content, metadata_json, created_at
                FROM memory_chunks
                WHERE source = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (source.value, limit),
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def count_by_source(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) AS count FROM memory_chunks GROUP BY source"
            ).fetchall()
        return {str(row["source"]): int(row["count"]) for row in rows}

    def update_sync_state(self, health: ConnectorHealth) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (source, last_sync_at, last_status, last_message, item_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_sync_at=excluded.last_sync_at,
                    last_status=excluded.last_status,
                    last_message=excluded.last_message,
                    item_count=excluded.item_count
                """,
                (
                    health.source.value,
                    health.last_sync_at.isoformat() if health.last_sync_at else None,
                    health.status.value,
                    health.message,
                    health.item_count,
                ),
            )

    def get_sync_states(self) -> list[ConnectorHealth]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, last_sync_at, last_status, last_message, item_count FROM sync_state"
            ).fetchall()
        results: list[ConnectorHealth] = []
        for row in rows:
            last_sync = row["last_sync_at"]
            results.append(
                ConnectorHealth(
                    source=SourceKind(str(row["source"])),
                    status=ConnectorStatus(str(row["last_status"])),
                    message=str(row["last_message"]),
                    last_sync_at=datetime.fromisoformat(last_sync) if last_sync else None,
                    item_count=int(row["item_count"]),
                )
            )
        return results

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> MemoryChunk:
        try:
            metadata = json.loads(str(row["metadata_json"]))
        except json.JSONDecodeError as exc:
            raise IngestError(f"Invalid metadata for chunk {row['chunk_id']}") from exc
        return MemoryChunk(
            chunk_id=str(row["chunk_id"]),
            source=SourceKind(str(row["source"])),
            title=str(row["title"]),
            content=str(row["content"]),
            metadata={str(k): str(v) for k, v in metadata.items()},
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )


_FTS_SPECIAL = _re.compile(r'[`*"()|:]')


def _sanitize_fts_query(query: str) -> str:
    cleaned = _FTS_SPECIAL.sub("", query).strip()
    if not cleaned:
        return query
    tokens = cleaned.split()
    return " OR ".join(tokens)
