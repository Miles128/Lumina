"""Xiaohongshu connector via autocli."""

from __future__ import annotations

import shutil

from secretary.connectors.base import BaseConnector
from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.ingest import chunk_text


class XiaohongshuConnector(BaseConnector):
    source = SourceKind.XIAOHONGSHU

    def is_configured(self) -> bool:
        return shutil.which("autocli") is not None

    def fetch(self) -> list[MemoryChunk]:
        chunks: list[MemoryChunk] = []
        chunks.extend(self._fetch_profile())
        chunks.extend(self._fetch_creator_notes())
        chunks.extend(self._fetch_feed())
        return chunks

    def _fetch_profile(self) -> list[MemoryChunk]:
        raw = self.run_command(
            ["autocli", "xiaohongshu", "creator-profile", "--format", "json"],
            timeout=90,
        )
        payload = self.parse_json_output(raw)
        if not isinstance(payload, dict):
            return []
        body = "\n".join(f"{key}: {value}" for key, value in payload.items())
        return chunk_text(
            source=self.source,
            key="creator-profile",
            title="小红书 · 创作者画像",
            body=body,
            metadata={"kind": "profile"},
        )

    def _fetch_creator_notes(self) -> list[MemoryChunk]:
        raw = self.run_command(
            ["autocli", "xiaohongshu", "creator-notes-summary", "--format", "json"],
            timeout=90,
        )
        payload = self.parse_json_output(raw)
        if isinstance(payload, list):
            notes = payload
        elif isinstance(payload, dict):
            notes = payload.get("notes", [])
        else:
            notes = []
        if not isinstance(notes, list):
            return []
        chunks: list[MemoryChunk] = []
        for index, note in enumerate(notes):
            if not isinstance(note, dict):
                continue
            title = str(note.get("title") or note.get("display_title") or f"笔记 {index + 1}")
            body = "\n".join(f"{key}: {value}" for key, value in note.items())
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=f"note:{title}:{index}",
                    title=f"小红书笔记 · {title}",
                    body=body,
                    metadata={"kind": "note"},
                )
            )
        return chunks

    def _fetch_feed(self) -> list[MemoryChunk]:
        raw = self.run_command(
            ["autocli", "xiaohongshu", "feed", "--format", "json", "--limit", "10"],
            timeout=90,
        )
        payload = self.parse_json_output(raw)
        items = payload if isinstance(payload, list) else []
        chunks: list[MemoryChunk] = []
        for index, item in enumerate(items[:10]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("desc") or f"推荐 {index + 1}")
            body = str(item.get("desc") or item.get("content") or title)
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=f"feed:{index}:{title[:40]}",
                    title=f"小红书推荐 · {title[:40]}",
                    body=body,
                    metadata={"kind": "feed"},
                )
            )
        return chunks
