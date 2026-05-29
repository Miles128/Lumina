"""Tests for memory summarizer state helpers."""

from __future__ import annotations

from secretary.services.memory_summarizer import MemorySummarizerService


def test_memory_summarizer_should_run_once_per_day(tmp_path) -> None:
    from secretary.config import Settings

    settings = Settings(data_dir=tmp_path, memory_summary_enabled=True, memory_summary_hour=23)
    service = MemorySummarizerService(settings, None, None)  # type: ignore[arg-type]
    assert service.should_run(23) is True
    assert service.should_run(8) is False
