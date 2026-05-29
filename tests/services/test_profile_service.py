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
    assert saved.markdown.startswith("# 我是用户")

    reset = service.reset_user_markdown()
    assert reset.is_user_edited is False
    assert reset.markdown == auto_before.auto_markdown


def test_local_excerpt_in_auto_profile(tmp_path: Path) -> None:
    settings = Settings(LUMINA_DATA_DIR=tmp_path)
    store = MemoryStore(tmp_path / "memory.db")
    user_store = UserProfileStore(tmp_path / "user_profile.md")
    profiler = LocalDocumentsProfiler(settings)
    profile_path = profiler.profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    LocalDocumentsProfile(
        generated_at=datetime.now(UTC),
        analyzed_files=1,
        excerpts=[DocumentExcerpt(file="resume.md", preview="负责产品运营")],
        source_files=["resume.md"],
    ).model_dump_json()

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
