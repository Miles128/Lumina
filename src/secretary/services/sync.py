"""Sync orchestration — local documents only; platform connectors retired."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from secretary.config import Settings
from secretary.connectors.base import BaseConnector
from secretary.connectors.registry import build_connectors
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
from secretary.exceptions import ConnectorError
from secretary.memory.db import MemoryStore
from secretary.services.local_documents_profiler import (
    LocalDocumentsPlatform,
    LocalDocumentsProfiler,
)
from secretary.services.profile_service import ProfileService
from secretary.services.shibei_service import ShibeiService
from secretary.services.user_profile_store import UserProfileStore

_RETIRED_MESSAGE = "平台连接器已移除；请使用 Shibei 知识库或标准 MCP"


@dataclass(frozen=True)
class SyncResult:
    source: SourceKind
    inserted: int
    health: ConnectorHealth


class SyncService:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        *,
        shibei_service: ShibeiService | None = None,
        mcp_manager: Any | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._shibei_service = shibei_service
        self._mcp_manager = mcp_manager
        self._connectors = build_connectors(self._settings)
        self._local_docs = LocalDocumentsPlatform(self._settings)
        self._local_profiler = LocalDocumentsProfiler(self._settings)

    def set_mcp_manager(self, mcp_manager: Any) -> None:
        """Inject McpManager after construction to break circular dependency."""
        self._mcp_manager = mcp_manager

    def list_connectors(self) -> list[BaseConnector]:
        return list(self._connectors)

    def reload_connectors(self) -> None:
        self._connectors = build_connectors(self._settings)
        self._local_docs = LocalDocumentsPlatform(self._settings)
        self._local_profiler = LocalDocumentsProfiler(self._settings)

    def sync_all(self) -> list[SyncResult]:
        results = [self.sync_source(SourceKind.LOCAL_DOCUMENTS)]
        self._persist_profile()
        self._maybe_import_shibei()
        return results

    def sync_source(self, source: SourceKind) -> SyncResult:
        if source is SourceKind.LOCAL_DOCUMENTS:
            return self._sync_local_documents()
        health = ConnectorHealth(
            source=source,
            status=ConnectorStatus.NOT_CONFIGURED,
            message=_RETIRED_MESSAGE,
        )
        self._store.update_sync_state(health)
        return SyncResult(source=source, inserted=0, health=health)

    def get_stored_health(self) -> list[ConnectorHealth]:
        """Read persisted status for local documents only."""
        stored = {item.source: item for item in self._store.get_sync_states()}
        return [
            self._local_docs.health_from_store(stored.get(SourceKind.LOCAL_DOCUMENTS))
        ]

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

    def _persist_profile(self) -> None:
        service = ProfileService(
            self._settings,
            self._store,
            self._local_profiler,
            UserProfileStore(self._settings.resolved_data_dir() / "user_profile.md"),
        )
        service.persist_after_sync()

    def _maybe_import_shibei(self) -> None:
        service = self._shibei_service
        if service is None or not service.is_enabled():
            return
        document = service._store.load()
        if not document.auto_import_on_sync:
            return
        native = service._try_native_config()
        if native is None or not native.sources:
            return
        if not service.is_available():
            return
        try:
            service.import_all(full=False)
        except Exception:
            return
