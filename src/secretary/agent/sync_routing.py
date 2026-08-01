"""Legacy sync-empty gating — retired.

Personal questions no longer require connector sync. Shibei / MEMORY.md /
local files are the supported paths. Kept as a stub so old imports do not break.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from secretary.core.types import SourceKind
from secretary.memory.db import MemoryStore

if TYPE_CHECKING:
    from secretary.services.shibei_service import ShibeiService
    from secretary.services.sync import SyncService


def detect_memory_sources(message: str) -> list[SourceKind]:
    """Retired: no longer maps questions onto connector SourceKinds."""
    del message
    return []


def resolve_sync_empty_reply(
    message: str,
    store: MemoryStore,
    sync_service: SyncService | None,
    *,
    memory_hits: int = 0,
    shibei_service: ShibeiService | None = None,
) -> str | None:
    """Always None — never block answers on connector sync state."""
    del message, store, sync_service, memory_hits, shibei_service
    return None
