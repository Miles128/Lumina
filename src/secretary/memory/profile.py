"""Rule-based user profile builder from memory chunks."""

from __future__ import annotations

from datetime import UTC, datetime

from secretary.core.types import MemoryChunk, ProfileSection, SourceKind, UserProfile
from secretary.memory.db import MemoryStore
from secretary.services.local_documents_profiler import LocalDocumentsProfile


class ProfileBuilder:
    """Build a factual CN-local user profile from ingested memory."""

    SECTIONS: dict[str, tuple[str, list[SourceKind]]] = {
        "work_rhythm": ("工作节奏", [SourceKind.FEISHU, SourceKind.EMAIL]),
        "reading_taste": ("阅读偏好", [SourceKind.WEREAD, SourceKind.WEIXIN_OA]),
        "content_interest": ("内容兴趣", [SourceKind.XIAOHONGSHU, SourceKind.WEIXIN_OA]),
        "information_habits": (
            "信息习惯",
            [SourceKind.EMAIL, SourceKind.CLOUD_DRIVE, SourceKind.FEISHU],
        ),
    }

    def __init__(
        self,
        store: MemoryStore,
        local_profile: LocalDocumentsProfile | None = None,
    ) -> None:
        self._store = store
        self._local_profile = local_profile

    def build(self) -> UserProfile:
        sections: list[ProfileSection] = []
        for key, (title, sources) in self.SECTIONS.items():
            chunks = self._collect_chunks(sources)
            content = self._summarize_section(key, chunks)
            sections.append(
                ProfileSection(
                    key=key,
                    title=title,
                    content=content,
                    evidence_count=len(chunks),
                )
            )

        sections.append(self._person_portrait_section())
        overview = self._build_overview(sections)
        markdown = self._render_markdown(overview, sections)
        return UserProfile(
            generated_at=datetime.now(UTC),
            sections=sections,
            markdown=markdown,
        )

    def _person_portrait_section(self) -> ProfileSection:
        profile = self._local_profile
        if profile is None or profile.analyzed_files == 0:
            return ProfileSection(
                key="person_portrait",
                title="本地文档摘录",
                content="暂无。请在设置中启用「本地文档」并执行同步。",
                evidence_count=0,
            )
        return ProfileSection(
            key="person_portrait",
            title="本地文档摘录",
            content=profile.to_section_text(),
            evidence_count=profile.analyzed_files,
        )

    def _collect_chunks(self, sources: list[SourceKind]) -> list[MemoryChunk]:
        chunks: list[MemoryChunk] = []
        for source in sources:
            chunks.extend(self._store.list_by_source(source, limit=50))
        return chunks

    def _summarize_section(self, key: str, chunks: list[MemoryChunk]) -> str:
        if not chunks:
            return "暂无数据。连接对应平台并同步后，这里会列出实际同步到的标题。"

        if key == "work_rhythm":
            titles = [chunk.title for chunk in chunks[:8] if chunk.title.strip()]
            if not titles:
                return "暂无数据。"
            return "同步记录：\n" + "\n".join(f"- {title}" for title in titles[:8])

        if key == "reading_taste":
            books = [
                chunk.metadata.get("book_title") or chunk.title
                for chunk in chunks[:10]
                if (chunk.metadata.get("book_title") or chunk.title).strip()
            ]
            if not books:
                return "暂无数据。"
            return "同步书目：\n" + "\n".join(f"- {title}" for title in books[:8])

        if key == "content_interest":
            titles = [chunk.title for chunk in chunks[:8] if chunk.title.strip()]
            if not titles:
                return "暂无数据。"
            return "同步内容：\n" + "\n".join(f"- {title}" for title in titles[:8])

        titles = [chunk.title for chunk in chunks[:8] if chunk.title.strip()]
        if not titles:
            return "暂无数据。"
        return "同步记录：\n" + "\n".join(f"- {title}" for title in titles[:8])

    def _build_overview(self, sections: list[ProfileSection]) -> str:
        active = [section.title for section in sections if section.evidence_count > 0]
        if not active:
            return "暂无自动摘要。你可以自己在下方编辑画像，或先同步数据源。"
        return "以下为各数据源实际同步内容的摘要，不含推测。你可以在设置中直接编辑画像。"

    def _render_markdown(self, overview: str, sections: list[ProfileSection]) -> str:
        return render_profile_markdown(overview, sections)


def render_profile_markdown(overview: str, sections: list[ProfileSection]) -> str:
    lines = [
        "# USER 画像",
        "",
        f"> 自动生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## 说明",
        overview,
        "",
    ]
    for section in sections:
        lines.extend([f"## {section.title}", section.content, ""])
    return "\n".join(lines).strip() + "\n"
