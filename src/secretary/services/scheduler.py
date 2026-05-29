"""Background sync and daily briefing scheduler."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from pathlib import Path

from secretary.config import Settings
from secretary.services.briefing import BriefingService
from secretary.services.memory_summarizer import MemorySummarizerService
from secretary.services.profile_service import ProfileService
from secretary.services.scheduled_think import ScheduledThinkService
from secretary.services.sync import SyncService

logger = logging.getLogger(__name__)

_BRIEFING_STATE = "briefing_state.json"


class BackgroundScheduler:
    def __init__(
        self,
        settings: Settings,
        sync_service: SyncService,
        profile_service: ProfileService,
        briefing_service: BriefingService,
        think_service: ScheduledThinkService | None = None,
        memory_summarizer: MemorySummarizerService | None = None,
    ) -> None:
        self._settings = settings
        self._sync_service = sync_service
        self._profile_service = profile_service
        self._briefing_service = briefing_service
        self._think_service = think_service
        self._memory_summarizer = memory_summarizer
        self._state_path = settings.resolved_data_dir() / _BRIEFING_STATE

    async def run_until_stopped(self, shutdown: asyncio.Event) -> None:
        if self._settings.auto_sync_enabled:
            await self._run_sync("startup")

        interval_seconds = max(self._settings.sync_interval_minutes, 1) * 60
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
                break
            except TimeoutError:
                pass

            if shutdown.is_set():
                break
            if self._settings.auto_sync_enabled:
                await self._run_sync("interval")
            await self._maybe_run_briefing()
            await self._maybe_run_think()
            await self._maybe_run_memory_summary()

    async def _run_sync(self, reason: str) -> None:
        try:
            results = await asyncio.to_thread(self._sync_service.sync_all)
            inserted = sum(item.inserted for item in results)
            logger.info("background sync (%s) complete, inserted=%s", reason, inserted)
        except Exception:
            logger.exception("background sync (%s) failed", reason)

    async def _maybe_run_briefing(self) -> None:
        if not self._settings.briefing_enabled:
            return
        now = datetime.now()
        if now.hour != self._settings.briefing_hour:
            return
        today = date.today().isoformat()
        if self._load_last_briefing_date() == today:
            return
        try:
            briefing = await asyncio.to_thread(
                self._briefing_service.generate,
                self._profile_service,
            )
            self._save_briefing_state(today, briefing)
            logger.info("daily briefing generated for %s", today)
        except Exception:
            logger.exception("daily briefing failed")

    async def _maybe_run_think(self) -> None:
        if self._think_service is None or not self._think_service.should_run():
            return
        try:
            await asyncio.to_thread(self._think_service.run)
        except Exception:
            logger.exception("scheduled think failed")

    async def _maybe_run_memory_summary(self) -> None:
        if self._memory_summarizer is None:
            return
        hour = datetime.now().hour
        if not self._memory_summarizer.should_run(hour):
            return
        try:
            await asyncio.to_thread(self._memory_summarizer.run)
        except Exception:
            logger.exception("memory summary failed")

    def _load_last_briefing_date(self) -> str:
        if not self._state_path.exists():
            return ""
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            value = payload.get("last_briefing_date")
            if isinstance(value, str):
                return value
        return ""

    def _save_briefing_state(self, day: str, briefing: str) -> None:
        payload = {
            "last_briefing_date": day,
            "generated_at": datetime.now().isoformat(),
            "markdown": briefing,
        }
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def load_latest_briefing(data_dir: Path) -> dict[str, str] | None:
        path = data_dir / _BRIEFING_STATE
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        markdown = payload.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return None
        generated_at = str(payload.get("generated_at", ""))
        return {"markdown": markdown, "generated_at": generated_at}
