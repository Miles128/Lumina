"""WeRead connector via autocli."""

from __future__ import annotations

import shutil

from secretary.connectors.base import BaseConnector
from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.ingest import chunk_text


class WeReadConnector(BaseConnector):
    source = SourceKind.WEREAD

    def is_configured(self) -> bool:
        return shutil.which("autocli") is not None

    def fetch(self) -> list[MemoryChunk]:
        chunks: list[MemoryChunk] = []
        chunks.extend(self._fetch_shelf())
        chunks.extend(self._fetch_highlights())
        return chunks

    def _fetch_shelf(self) -> list[MemoryChunk]:
        raw = self.run_command(["autocli", "weread", "shelf", "--format", "json"], timeout=90)
        payload = self.parse_json_output(raw)
        books = payload if isinstance(payload, list) else []
        chunks: list[MemoryChunk] = []
        for index, book in enumerate(books):
            if not isinstance(book, dict):
                continue
            title = str(book.get("title") or book.get("bookTitle") or f"书籍 {index + 1}")
            author = str(book.get("author") or "")
            progress = str(book.get("progress") or book.get("readProgress") or "")
            body = f"书名: {title}\n作者: {author}\n进度: {progress}"
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=f"shelf:{title}",
                    title=f"微信读书 · {title}",
                    body=body,
                    metadata={"book_title": title, "author": author},
                )
            )
        return chunks

    def _fetch_highlights(self) -> list[MemoryChunk]:
        raw = self.run_command(["autocli", "weread", "highlights", "--format", "json"], timeout=90)
        payload = self.parse_json_output(raw)
        highlights = payload if isinstance(payload, list) else []
        chunks: list[MemoryChunk] = []
        for index, item in enumerate(highlights):
            if not isinstance(item, dict):
                continue
            book_title = str(item.get("bookTitle") or item.get("title") or "未知书籍")
            quote = str(item.get("markText") or item.get("content") or "")
            note = str(item.get("note") or "")
            body = f"划线: {quote}\n笔记: {note}".strip()
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=f"highlight:{book_title}:{index}",
                    title=f"微信读书划线 · {book_title}",
                    body=body,
                    metadata={"book_title": book_title},
                )
            )
        return chunks
