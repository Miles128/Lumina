"""Tests for editable user profile."""

from datetime import UTC, datetime
from pathlib import Path

from secretary.config import Settings
from secretary.memory.db import MemoryStore
from secretary.services.local_documents_profiler import (
    DocumentExcerpt,
    LocalDocumentsProfile,
    LocalDocumentsProfiler,
)
from secretary.services.profile_service import ProfileService
from secretary.services.user_profile_store import UserProfileStore


def test_user_can_override_auto_profile(tmp_path: Path) -> None:
    settings = Settings(LUMINA_DATA_DIR=tmp_path)
    store = MemoryStore(tmp_path / "memory.db")
    user_store = UserProfileStore(tmp_path / "user_profile.md")
    profiler = LocalDocumentsProfiler(settings)
    service = ProfileService(settings, store, profiler, user_store)

    auto_before = service.get_view()
    saved = service.save_user_markdown("# 我是用户自己写的画像\n")
    assert saved.is_user_edited is True
    assert saved.user_markdown.startswith("# 我是用户")

    reset = service.reset_user_markdown()
    assert reset.is_user_edited is False
    assert reset.markdown == auto_before.auto_markdown


def test_save_user_profile_strips_chat_facts_section(tmp_path: Path) -> None:
    settings = Settings(LUMINA_DATA_DIR=tmp_path)
    store = MemoryStore(tmp_path / "memory.db")
    user_store = UserProfileStore(tmp_path / "user_profile.md")
    profiler = LocalDocumentsProfiler(settings)
    service = ProfileService(settings, store, profiler, user_store)

    service.append_chat_fact("在杭州工作")
    saved = service.save_user_markdown(
        "# 我的画像\n\n## 对话中了解到的信息\n\n- 在杭州工作\n"
    )
    assert saved.user_markdown == "# 我的画像"
    assert "在杭州工作" in saved.chat_facts_markdown
    assert saved.markdown.count("在杭州工作") == 1


def test_local_excerpt_in_auto_profile(tmp_path: Path) -> None:
    settings = Settings(LUMINA_DATA_DIR=tmp_path)
    store = MemoryStore(tmp_path / "memory.db")
    user_store = UserProfileStore(tmp_path / "user_profile.md")
    profiler = LocalDocumentsProfiler(settings)
    profile_path = profiler.profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        LocalDocumentsProfile(
            generated_at=datetime.now(UTC),
            analyzed_files=1,
            excerpts=[DocumentExcerpt(file="resume.md", preview="负责产品运营")],
            source_files=["resume.md"],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    service = ProfileService(settings, store, profiler, user_store)
    view = service.get_view()
    portrait = next(item for item in view.sections if item["key"] == "person_portrait")
    assert "负责产品运营" in str(portrait["content"])


def test_append_chat_fact_merges_into_profile_view(tmp_path: Path) -> None:
    settings = Settings(LUMINA_DATA_DIR=tmp_path)
    store = MemoryStore(tmp_path / "memory.db")
    user_store = UserProfileStore(tmp_path / "user_profile.md")
    profiler = LocalDocumentsProfiler(settings)
    service = ProfileService(settings, store, profiler, user_store)

    service.append_chat_fact("在北京从事产品设计")
    view = service.get_view()
    assert "在北京从事产品设计" in view.markdown
    assert (tmp_path / "profile_chat_facts.md").exists()

    service.append_chat_fact("在北京从事产品设计")
    view2 = service.get_view()
    assert view2.markdown.count("在北京从事产品设计") == 1


def test_clear_chat_derived_facts(tmp_path: Path) -> None:
    from secretary.services.profile_service import clear_polluted_derived_state

    settings = Settings(LUMINA_DATA_DIR=tmp_path)
    store = MemoryStore(tmp_path / "memory.db")
    user_store = UserProfileStore(tmp_path / "user_profile.md")
    profiler = LocalDocumentsProfiler(settings)
    service = ProfileService(settings, store, profiler, user_store)

    service.append_chat_fact("幻觉书目：《启示录》")
    assert (tmp_path / "profile_chat_facts.md").exists()
    (tmp_path / "think_state.json").write_text("{}", encoding="utf-8")

    cleared = service.clear_chat_derived_facts()
    assert "幻觉书目" not in cleared.markdown
    assert not (tmp_path / "profile_chat_facts.md").exists()
    removed = clear_polluted_derived_state(tmp_path)
    assert "think_state.json" in removed
