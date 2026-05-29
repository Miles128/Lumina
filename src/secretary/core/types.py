"""Shared domain types."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SourceKind(StrEnum):
    FEISHU = "feishu"
    EMAIL = "email"
    WEREAD = "weread"
    XIAOHONGSHU = "xiaohongshu"
    WEIXIN_OA = "weixin_oa"
    CLOUD_DRIVE = "cloud_drive"
    LOCAL_DOCUMENTS = "local_documents"


class ConnectorStatus(StrEnum):
    READY = "ready"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


@dataclass(frozen=True)
class MemoryChunk:
    chunk_id: str
    source: SourceKind
    title: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ConnectorHealth:
    source: SourceKind
    status: ConnectorStatus
    message: str
    last_sync_at: datetime | None = None
    item_count: int = 0


@dataclass(frozen=True)
class ProfileSection:
    key: str
    title: str
    content: str
    evidence_count: int


@dataclass(frozen=True)
class UserProfile:
    generated_at: datetime
    sections: list[ProfileSection]
    markdown: str
