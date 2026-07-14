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


SOURCE_LABELS: dict[SourceKind, str] = {
    SourceKind.FEISHU: "飞书",
    SourceKind.EMAIL: "邮箱",
    SourceKind.WEREAD: "微信读书",
    SourceKind.XIAOHONGSHU: "小红书",
    SourceKind.WEIXIN_OA: "微信公众号",
    SourceKind.CLOUD_DRIVE: "云盘",
    SourceKind.LOCAL_DOCUMENTS: "本地文档",
}


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
