"""Local cloud-drive folder connector."""

from __future__ import annotations

from pathlib import Path

from secretary.connectors.base import BaseConnector
from secretary.core.types import MemoryChunk, SourceKind
from secretary.exceptions import ConnectorNotConfiguredError
from secretary.memory.ingest import chunk_text

TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".log"}


class CloudDriveConnector(BaseConnector):
    source = SourceKind.CLOUD_DRIVE

    def is_configured(self) -> bool:
        return bool(self._settings.parsed_cloud_paths())

    def fetch(self) -> list[MemoryChunk]:
        paths = self._settings.parsed_cloud_paths()
        if not paths:
            raise ConnectorNotConfiguredError("CLOUD_DRIVE_PATHS is empty")

        chunks: list[MemoryChunk] = []
        for root in paths:
            if not root.exists():
                continue
            chunks.extend(self._scan_path(root))
        return chunks

    def _scan_path(self, root: Path) -> list[MemoryChunk]:
        chunks: list[MemoryChunk] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if path.stat().st_size > 512_000:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            relative = str(path.relative_to(root))
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=str(path),
                    title=f"网盘文件 · {relative}",
                    body=content,
                    metadata={"path": str(path), "root": str(root)},
                )
            )
        return chunks
