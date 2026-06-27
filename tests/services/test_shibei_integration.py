"""Tests for Shibei integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from secretary.services.shibei_config import ShibeiConfigDocument, ShibeiConfigStore
from secretary.services.shibei_service import ShibeiService, _format_search


def _write_shibei_project(root: Path, *, sources: list[str] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "src" / "shibei").mkdir(parents=True)
    (root / "src" / "shibei" / "__init__.py").write_text("", encoding="utf-8")
    source_lines = "\n".join(f"  - {item}" for item in (sources or ["/tmp/notes"]))
    (root / "config.yaml").write_text(
        f"chroma:\n  path: {root / 'db'}\n  collection: test_kb\n  search_engine: bm25\n"
        f"sources:\n{source_lines}\n",
        encoding="utf-8",
    )


def test_shibei_resolve_config_path(tmp_path: Path) -> None:
    shibei_root = tmp_path / "shibei"
    _write_shibei_project(shibei_root)
    store = ShibeiConfigStore(tmp_path / "shibei.json", data_dir=tmp_path / "data")
    store.save(ShibeiConfigDocument(install_path=str(shibei_root)))
    assert store.resolve_config_path() == (shibei_root / "config.yaml").resolve()


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
    shibei_root = tmp_path / "shibei"
    _write_shibei_project(shibei_root)
    store = ShibeiConfigStore(tmp_path / "shibei.json", data_dir=tmp_path / "data")
    store.save(ShibeiConfigDocument(install_path=str(shibei_root)))
    service = ShibeiService(store)

    fake_brain = MagicMock()
    fake_brain.search.return_value = {"query": "test", "total": 0, "results": []}

    with patch.object(service, "_resolve_src_path", return_value=shibei_root / "src"):
        with patch.dict("sys.modules", {"shibei": MagicMock(Shibei=lambda _p: fake_brain)}):
            output = service.search("test")
    assert "未在 Shibei" in output


def test_shibei_read_source_within_root(tmp_path: Path) -> None:
    shibei_root = tmp_path / "shibei"
    notes = tmp_path / "notes"
    notes.mkdir()
    note = notes / "hello.md"
    note.write_text("# Hello", encoding="utf-8")
    _write_shibei_project(shibei_root, sources=[str(notes)])
    store = ShibeiConfigStore(tmp_path / "shibei.json", data_dir=tmp_path / "data")
    store.save(ShibeiConfigDocument(install_path=str(shibei_root)))
    service = ShibeiService(store)

    fake_cfg = MagicMock()
    fake_cfg.sources = [str(notes)]
    with patch.object(service, "_try_native_config", return_value=fake_cfg):
        payload = service.read_source(str(note))
    assert payload["name"] == "hello.md"
    assert "# Hello" in payload["content"]


def test_shibei_read_source_rejects_outside_root(tmp_path: Path) -> None:
    shibei_root = tmp_path / "shibei"
    allowed = tmp_path / "notes"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    _write_shibei_project(shibei_root, sources=[str(allowed)])
    store = ShibeiConfigStore(tmp_path / "shibei.json", data_dir=tmp_path / "data")
    store.save(ShibeiConfigDocument(install_path=str(shibei_root)))
    service = ShibeiService(store)

    fake_cfg = MagicMock()
    fake_cfg.sources = [str(allowed)]
    with patch.object(service, "_try_native_config", return_value=fake_cfg):
        with pytest.raises(ValueError, match="监控范围"):
            service.read_source(str(outside))


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
