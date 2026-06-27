"""Detect personal-data questions with empty sync stores (PRD v0.1.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from secretary.agent.grounding import is_personal_memory_question
from secretary.core.types import ConnectorStatus, SourceKind
from secretary.memory.db import MemoryStore

if TYPE_CHECKING:
    from secretary.services.sync import SyncService

SOURCE_LABELS: dict[SourceKind, str] = {
    SourceKind.FEISHU: "飞书",
    SourceKind.EMAIL: "邮箱",
    SourceKind.WEREAD: "微信读书",
    SourceKind.XIAOHONGSHU: "小红书",
    SourceKind.WEIXIN_OA: "微信公众号",
    SourceKind.CLOUD_DRIVE: "云盘",
    SourceKind.LOCAL_DOCUMENTS: "本地文档",
}

_SOURCE_MARKERS: dict[SourceKind, tuple[str, ...]] = {
    SourceKind.WEREAD: (
        "微信读书",
        "weread",
        "在读",
        "读过",
        "读书",
        "书目",
        "书籍",
        "书架",
        "最近读",
    ),
    SourceKind.FEISHU: ("飞书", "lark", "日程", "会议", "妙记", "多维表格"),
    SourceKind.EMAIL: ("邮件", "邮箱", "imap", "收件箱", "未读邮件"),
    SourceKind.XIAOHONGSHU: ("小红书", "redbook", "笔记收藏"),
    SourceKind.WEIXIN_OA: ("公众号", "订阅号"),
    SourceKind.CLOUD_DRIVE: ("云盘", "网盘", "云存储"),
    SourceKind.LOCAL_DOCUMENTS: ("本地文档", "本地文件分析"),
}


def detect_memory_sources(message: str) -> list[SourceKind]:
    text = message.strip()
    if not text:
        return []
    lowered = text.lower()
    matched: list[SourceKind] = []
    for source, markers in _SOURCE_MARKERS.items():
        if any(marker in text or marker in lowered for marker in markers):
            matched.append(source)
    return matched


def resolve_sync_empty_reply(
    message: str,
    store: MemoryStore,
    sync_service: SyncService | None,
    *,
    memory_hits: int = 0,
) -> str | None:
    """Return a user-facing reply when synced data is required but missing."""
    if not is_personal_memory_question(message):
        return None

    counts = store.count_by_source()
    sources = detect_memory_sources(message)

    if sources:
        missing = [source for source in sources if counts.get(source.value, 0) == 0]
        if not missing:
            return None
        return _missing_source_reply(missing[0], sync_service)

    if memory_hits > 0 or sum(counts.values()) > 0:
        return None
    return _generic_sync_reply()


def _missing_source_reply(source: SourceKind, sync_service: SyncService | None) -> str:
    label = SOURCE_LABELS.get(source, source.value)
    health = _health_for(source, sync_service)
    if health is None or health.status is ConnectorStatus.NOT_CONFIGURED:
        return (
            f"我还不知道你的{label}数据。\n\n"
            f"请先在 **设置 → 平台** 里配置{label}，然后点右上角 **「同步」**，再问我这个问题。"
        )
    if health.status is ConnectorStatus.ERROR:
        detail = health.message.strip() or "同步失败"
        return (
            f"上次同步{label}时出错：{detail}\n\n"
            f"请检查设置后重新点 **「同步」**，再问我这个问题。"
        )
    if health.item_count <= 0:
        return (
            f"本地还没有{label}的同步记录。\n\n"
            f"请先点右上角 **「同步」**，我才能根据真实数据回答，不会编造书单或记录。"
        )
    return _generic_sync_reply()


def _generic_sync_reply() -> str:
    return (
        "本地还没有同步过的个人数据。\n\n"
        "请先点右上角 **「同步」**（或在设置里配置数据源），"
        "我才能回答阅读、邮件、飞书等个人记录类问题，不会凭空编造。"
    )


def _health_for(source: SourceKind, sync_service: SyncService | None):
    if sync_service is None:
        return None
    for item in sync_service.get_stored_health():
        if item.source is source:
            return item
    return None
