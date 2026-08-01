"""Tests for memory summarizer state helpers."""

from __future__ import annotations

from secretary.services.memory_summarizer import MemorySummarizerService


def test_memory_summarizer_should_run_once_per_day(tmp_path) -> None:
    from secretary.config import Settings
    from secretary.services.agent_config import AgentConfigStore

    settings = Settings(data_dir=tmp_path, memory_summary_enabled=True, memory_summary_hour=23)
    store = AgentConfigStore(tmp_path / "agent.json")
    service = MemorySummarizerService(settings, None, store)  # type: ignore[arg-type]
    assert service.should_run(23) is True
    assert service.should_run(8) is False
