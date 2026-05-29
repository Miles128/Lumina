"""Sync orchestration across connectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from secretary.config import Settings
from secretary.connectors.base import BaseConnector
from secretary.connectors.registry import build_connectors
from secretary.core.types import ConnectorHealth, ConnectorStatus, MemoryChunk, SourceKind
from secretary.exceptions import ConnectorError
from secretary.memory.db import MemoryStore
from secretary.memory.kb import KnowledgeWorkspace
from secretary.services.local_documents_profiler import (
    LocalDocumentsPlatform,
    LocalDocumentsProfiler,
)
from secretary.services.profile_service import ProfileService
from secretary.services.user_profile_store import UserProfileStore

BROWSER_SYNC_SOURCES = frozenset({SourceKind.WEREAD, SourceKind.XIAOHONGSHU})


@dataclass(frozen=True)
class SyncResult:
    source: SourceKind
    inserted: int
    health: ConnectorHealth


class SyncService:
    def __init__(self, settings: Settings, store: MemoryStore) -> None:
        self._settings = settings
        self._store = store
        self._connectors = build_connectors(self._settings)
        self._local_docs = LocalDocumentsPlatform(self._settings)
        self._local_profiler = LocalDocumentsProfiler(self._settings)
        self._store.purge_source(SourceKind.LOCAL_DOCUMENTS)

    def list_connectors(self) -> list[BaseConnector]:
        return list(self._connectors)

    def reload_connectors(self) -> None:
        self._connectors = build_connectors(self._settings)
        self._local_docs = LocalDocumentsPlatform(self._settings)
        self._local_profiler = LocalDocumentsProfiler(self._settings)

    def sync_all(self, *, include_browser_sources: bool = False) -> list[SyncResult]:
        results: list[SyncResult] = []
        for connector in self._connectors:
            if not include_browser_sources and connector.source in BROWSER_SYNC_SOURCES:
                continue
            results.append(self.sync_source(connector.source))
        results.append(self.sync_source(SourceKind.LOCAL_DOCUMENTS))
        self._persist_profile()
        self.export_kb_from_memory()
        return results

    def sync_source(self, source: SourceKind) -> SyncResult:
        if source is SourceKind.LOCAL_DOCUMENTS:
            return self._sync_local_documents()
        connector = self._get_connector(source)
        if not connector.is_configured():
            health = ConnectorHealth(
                source=source,
                status=ConnectorStatus.NOT_CONFIGURED,
                message="未配置",
            )
            self._store.update_sync_state(health)
            return SyncResult(source=source, inserted=0, health=health)

        try:
            chunks = connector.fetch()
            inserted = self._store.upsert_chunks(chunks)
            health = ConnectorHealth(
                source=source,
                status=ConnectorStatus.READY,
                message="同步成功",
                last_sync_at=datetime.now(UTC),
                item_count=inserted,
            )
        except ConnectorError as exc:
            health = ConnectorHealth(
                source=source,
                status=ConnectorStatus.ERROR,
                message=str(exc),
                last_sync_at=datetime.now(UTC),
            )
            inserted = 0

        self._store.update_sync_state(health)
        return SyncResult(source=source, inserted=inserted, health=health)

    def get_health(self) -> list[ConnectorHealth]:
        stored = {item.source: item for item in self._store.get_sync_states()}
        health: list[ConnectorHealth] = []
        for connector in self._connectors:
            if connector.source in stored:
                health.append(stored[connector.source])
                continue
            health.append(connector.health())
        health.append(
            self._local_docs.health_from_store(stored.get(SourceKind.LOCAL_DOCUMENTS))
        )
        return health

    def get_stored_health(self) -> list[ConnectorHealth]:
        """Read persisted connector status only — no live CLI/network checks."""
        stored = {item.source: item for item in self._store.get_sync_states()}
        health: list[ConnectorHealth] = []
        for connector in self._connectors:
            item = stored.get(connector.source)
            if item is not None:
                health.append(item)
                continue
            health.append(
                ConnectorHealth(
                    source=connector.source,
                    status=ConnectorStatus.NOT_CONFIGURED,
                    message="未配置",
                )
            )
        health.append(
            self._local_docs.health_from_store(stored.get(SourceKind.LOCAL_DOCUMENTS))
        )
        return health

    def _sync_local_documents(self) -> SyncResult:
        source = SourceKind.LOCAL_DOCUMENTS
        if not self._local_docs.is_configured():
            health = ConnectorHealth(
                source=source,
                status=ConnectorStatus.NOT_CONFIGURED,
                message="未启用",
            )
            self._store.update_sync_state(health)
            return SyncResult(source=source, inserted=0, health=health)

        self._store.purge_source(source)
        try:
            profile = self._local_profiler.analyze_and_save()
            chunks = self._local_profiler.memory_chunks(profile)
            inserted = self._store.upsert_chunks(chunks)
            health = ConnectorHealth(
                source=source,
                status=ConnectorStatus.READY,
                message=(
                    f"已分析 {profile.analyzed_files} 篇文档，"
                    f"写入记忆 {inserted} 条，跳过 {profile.skipped_files} 个"
                ),
                last_sync_at=datetime.now(UTC),
                item_count=inserted,
            )
        except ConnectorError as exc:
            health = ConnectorHealth(
                source=source,
                status=ConnectorStatus.ERROR,
                message=str(exc),
                last_sync_at=datetime.now(UTC),
            )
            inserted = 0

        self._store.update_sync_state(health)
        if health.status is ConnectorStatus.READY:
            self._persist_profile()
        return SyncResult(source=source, inserted=inserted, health=health)

    def _get_connector(self, source: SourceKind) -> BaseConnector:
        for connector in self._connectors:
            if connector.source is source:
                return connector
        raise ConnectorError(f"unknown source: {source}")

    def _persist_profile(self) -> None:
        service = ProfileService(
            self._settings,
            self._store,
            self._local_profiler,
            UserProfileStore(self._settings.resolved_data_dir() / "user_profile.md"),
        )
        service.persist_after_sync()

    def export_kb_from_memory(self) -> int:
        workspace = KnowledgeWorkspace(self._settings.resolved_data_dir() / "workspace")
        chunks: list[MemoryChunk] = []
        for source in SourceKind:
            chunks.extend(self._store.list_by_source(source, limit=200))
        return workspace.export_chunks(chunks)
