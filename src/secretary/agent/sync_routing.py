"""Detect personal-data questions with empty sync stores (PRD v0.1.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from secretary.agent.grounding import is_personal_memory_question
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
from secretary.memory.db import MemoryStore
from secretary.services.shibei_service import shibei_ready_for_memory_read

if TYPE_CHECKING:
    from secretary.services.shibei_service import ShibeiService
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
    shibei_service: ShibeiService | None = None,
) -> str | None:
    """Return a user-facing reply when synced connector data is required but missing."""
    from secretary.agent.grounding import is_memory_write_request

    if is_memory_write_request(message):
        return None
    if shibei_ready_for_memory_read(shibei_service):
        return None
    if not is_personal_memory_question(message):
        return None

    counts = store.count_by_source()
    sources = detect_memory_sources(message)

    if sources:
        missing = [source for source in sources if counts.get(source.value, 0) == 0]
        if not missing:
            return None
        return _missing_source_reply(missing[0], sync_service, shibei_service=shibei_service)

    if memory_hits > 0 or sum(counts.values()) > 0:
        return None
    return _generic_sync_reply(shibei_service=shibei_service)


def _missing_source_reply(
    source: SourceKind,
    sync_service: SyncService | None,
    *,
    shibei_service: ShibeiService | None = None,
) -> str:
    label = SOURCE_LABELS.get(source, source.value)
    shibei_hint = (
        "也可先在 **设置 → Shibei 知识库** 检索已索引文档（推荐）。"
        if shibei_service is not None and shibei_service.is_enabled()
        else ""
    )
    health = _health_for(source, sync_service)
    if health is None or health.status is ConnectorStatus.NOT_CONFIGURED:
        return (
            f"我还不知道你的{label}数据。\n\n"
            f"请先在 **设置 → 平台** 里配置{label}，然后点右上角 **「同步」**（备选）。"
            f"{shibei_hint}"
        )
    if health.status is ConnectorStatus.ERROR:
        detail = health.message.strip() or "同步失败"
        return (
            f"上次同步{label}时出错：{detail}\n\n"
            f"请检查设置后重新点 **「同步」**，再问我这个问题。{shibei_hint}"
        )
    if health.item_count <= 0:
        return (
            f"本地还没有{label}的 Lumina 同步记录。\n\n"
            f"建议先用 shibei_search 查 Shibei 知识库；"
            f"若无结果，可点右上角 **「同步」** 导入{label}数据（备选）。"
        )
    return _generic_sync_reply(shibei_service=shibei_service)


def _generic_sync_reply(*, shibei_service: ShibeiService | None = None) -> str:
    if shibei_service is not None and shibei_service.is_enabled():
        return (
            "Shibei 知识库尚未就绪，本地也没有同步过的连接器数据。\n\n"
            "请先在 **设置 → Shibei 知识库** 填写安装路径并建立索引；"
            "或在 Shibei 应用里 import 监控文件夹。"
            "连接器同步（微信读书、飞书等）是备选方案，可点右上角 **「同步」**。"
        )
    return (
        "本地还没有可用的个人知识库。\n\n"
        "请先在 **设置 → Shibei 知识库** 启用并索引你的笔记/文档（推荐）；"
        "或点右上角 **「同步」** 导入微信读书、飞书等连接器数据（备选）。"
        "没有真实数据前，我不会编造个人记录。"
    )


def _health_for(source: SourceKind, sync_service: SyncService | None) -> ConnectorHealth | None:
    if sync_service is None:
        return None
    for item in sync_service.get_stored_health():
        if item.source is source:
            return item
    return None
