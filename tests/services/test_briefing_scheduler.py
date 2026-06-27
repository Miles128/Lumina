"""Tests for briefing and scheduler."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.services.briefing import BriefingService
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.services.profile_service import ProfileService
from secretary.services.scheduler import BackgroundScheduler
from secretary.services.sync import SyncService
from secretary.services.user_profile_store import UserProfileStore


def _profile_service(tmp_path: Path) -> ProfileService:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    profiler = LocalDocumentsProfiler(settings)
    user_store = UserProfileStore(settings.resolved_data_dir() / "user_profile.md")
    return ProfileService(settings, store, profiler, user_store)


def test_briefing_rule_based(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    service = BriefingService(settings, store)
    markdown = service.generate(_profile_service(tmp_path))
    assert "# 今日简报" in markdown
    assert "同步" in markdown


def _run_async(coro: object) -> None:
    """Run coroutine in a fresh loop (Playwright E2E may leave a loop on the main thread)."""
    error: list[BaseException] = []

    def _target() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)  # type: ignore[arg-type]
        except BaseException as exc:
            error.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if error:
        raise error[0]


def test_scheduler_saves_briefing_state(tmp_path: Path) -> None:
    hour = datetime.now().hour
    settings = Settings(
        data_dir=tmp_path / "data",
        auto_sync_enabled=False,
        briefing_enabled=True,
        briefing_hour=hour,
    )
    store = MemoryStore(settings.resolved_data_dir() / "memory.db")
    sync = SyncService(settings, store)
    profile_service = _profile_service(tmp_path)
    briefing = BriefingService(settings, store)
    scheduler = BackgroundScheduler(settings, sync, profile_service, briefing)

    with patch.object(briefing, "generate", return_value="# 今日简报\n\n测试"):
        _run_async(scheduler._maybe_run_briefing())

    payload = BackgroundScheduler.load_latest_briefing(settings.resolved_data_dir())
    assert payload is not None
    assert "今日简报" in payload["markdown"]
