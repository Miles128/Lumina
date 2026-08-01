"""sync_empty routing retired with platform connectors."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.sync_routing import resolve_sync_empty_reply
from secretary.config import Settings
from secretary.memory.db import MemoryStore


def test_resolve_sync_empty_always_none(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    assert (
        resolve_sync_empty_reply(
            "我微信读书最近在读什么",
            store,
            None,
            memory_hits=0,
        )
        is None
    )
    assert (
        resolve_sync_empty_reply(
            "帮我同步全部数据",
            store,
            None,
            memory_hits=0,
        )
        is None
    )
