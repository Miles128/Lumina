"""Tests for Shibei integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from secretary.services.shibei_config import ShibeiConfigStore
from secretary.services.shibei_service import ShibeiService, _format_search


def test_shibei_config_sync_yaml(tmp_path: Path) -> None:
    store = ShibeiConfigStore(tmp_path / "shibei.json", data_dir=tmp_path / "data")
    document = store.load()
    document = document.model_copy(
        update={"sources": ["/tmp/notes", "/tmp/projects"], "search_engine": "bm25"}
    )
    yaml_path = store.sync_yaml(document)
    text = yaml_path.read_text(encoding="utf-8")
    assert "/tmp/notes" in text
    assert "search_engine: bm25" in text
    assert "collection: lumina_kb" in text


def test_format_search_empty() -> None:
    assert "未在 Shibei" in _format_search({"query": "x", "total": 0, "results": []})


def test_format_search_results() -> None:
    text = _format_search(
        {
            "query": "风控",
            "total": 1,
            "results": [{"rank": 1, "source": "a.md", "score": 0.9, "tags": "finance", "text": "银行风控"}],
        }
    )
    assert "a.md" in text
    assert "银行风控" in text


def test_shibei_service_search_mock(tmp_path: Path) -> None:
    store = ShibeiConfigStore(tmp_path / "shibei.json", data_dir=tmp_path / "data")
    store.save(store.load())
    service = ShibeiService(store)

    fake_brain = MagicMock()
    fake_brain.search.return_value = {"query": "test", "total": 0, "results": []}

    with patch.object(service, "_resolve_src_path", return_value=tmp_path):
        with patch.dict("sys.modules", {"shibei": MagicMock(Shibei=lambda _p: fake_brain)}):
            output = service.search("test")
    assert "未在 Shibei" in output


def test_build_tools_includes_shibei_when_enabled(tmp_path: Path) -> None:
    from secretary.agent.chat_service import ChatService
    from secretary.agent.skills import SkillManager
    from secretary.config import Settings
    from secretary.memory.db import MemoryStore
    from secretary.services.local_documents_profiler import LocalDocumentsProfiler
    from secretary.services.profile_service import ProfileService
    from secretary.services.user_profile_store import UserProfileStore

    settings = Settings(data_dir=tmp_path / "data", prompt_gate_enabled=False)
    memory = MemoryStore(settings.resolved_data_dir() / "memory.db")
    profile = ProfileService(
        settings,
        memory,
        LocalDocumentsProfiler(settings),
        UserProfileStore(settings.resolved_data_dir() / "user_profile.md"),
    )
    shibei_store = ShibeiConfigStore(settings.resolved_data_dir() / "shibei.json", data_dir=settings.resolved_data_dir())
    shibei = ShibeiService(shibei_store)
    chat = ChatService(settings, memory, profile, SkillManager(settings.resolved_data_dir()), shibei_service=shibei)
    names = {tool.name for tool in chat._build_tools()}
    assert "shibei_search" in names
    assert "shibei_import" in names
