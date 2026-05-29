"""Tests for profile builder."""

from datetime import UTC, datetime
from pathlib import Path

from secretary.core.types import MemoryChunk, SourceKind
from secretary.memory.db import MemoryStore
from secretary.memory.profile import ProfileBuilder
from secretary.services.local_documents_profiler import DocumentExcerpt, LocalDocumentsProfile


def test_profile_builder_with_chunks(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.upsert_chunks(
        [
            MemoryChunk(
                chunk_id="1",
                source=SourceKind.WEREAD,
                title="微信读书 · 深度工作",
                content="专注 专注 专注",
                metadata={"book_title": "深度工作"},
            ),
            MemoryChunk(
                chunk_id="2",
                source=SourceKind.XIAOHONGSHU,
                title="小红书推荐 · AI 工具",
                content="AI 工具 效率 自动化",
            ),
        ]
    )

    profile = ProfileBuilder(store).build()
    assert "USER 画像" in profile.markdown
    reading = next(section for section in profile.sections if section.key == "reading_taste")
    assert "深度工作" in reading.content
    assert "高频兴趣词" not in profile.markdown


def test_profile_person_portrait_section(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    local = LocalDocumentsProfile(
        generated_at=datetime.now(UTC),
        analyzed_files=1,
        skipped_files=0,
        excerpts=[DocumentExcerpt(file="resume.md", preview="负责产品运营")],
        source_files=["resume.md"],
    )
    profile = ProfileBuilder(store, local_profile=local).build()
    section = next(item for item in profile.sections if item.key == "person_portrait")
    assert "负责产品运营" in section.content
    assert "已从" in section.content
