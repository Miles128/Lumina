"""Merge auto profile with user edits."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from secretary.agent.llm_config import resolve_llm_config
from secretary.config import Settings
from secretary.core.types import UserProfile
from secretary.memory.db import MemoryStore
from secretary.memory.kb import KnowledgeWorkspace
from secretary.services.agent_config import AgentConfigStore
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.memory.profile import ProfileBuilder
from secretary.services.user_profile_store import UserProfileStore


class ProfileView(BaseModel):
    generated_at: datetime
    markdown: str
    auto_markdown: str
    user_markdown: str
    is_user_edited: bool
    sections: list[dict[str, str | int]] = Field(default_factory=list)


class ProfileService:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        local_profiler: LocalDocumentsProfiler,
        user_store: UserProfileStore,
    ) -> None:
        self._settings = settings
        self._store = store
        self._local_profiler = local_profiler
        self._user_store = user_store

    def build_auto(self) -> UserProfile:
        agent_store = AgentConfigStore(self._settings.resolved_data_dir() / "agent.json")
        llm_config = resolve_llm_config(self._settings, agent_store)
        from secretary.services.profile_summarizer import build_profile

        return build_profile(
            self._store,
            self._local_profiler.load_profile(),
            llm_config,
        )

    def get_view(self) -> ProfileView:
        rule_auto = ProfileBuilder(
            self._store,
            local_profile=self._local_profiler.load_profile(),
        ).build()
        cached_auto = self._load_cached_auto_markdown()
        auto_markdown = cached_auto if cached_auto else rule_auto.markdown
        user = self._user_store.load()
        user_markdown = user.markdown.strip()
        display = user_markdown if user_markdown else auto_markdown
        return ProfileView(
            generated_at=rule_auto.generated_at,
            markdown=display,
            auto_markdown=auto_markdown,
            user_markdown=user_markdown,
            is_user_edited=bool(user_markdown),
            sections=[
                {
                    "key": section.key,
                    "title": section.title,
                    "content": section.content,
                    "evidence_count": section.evidence_count,
                }
                for section in rule_auto.sections
            ],
        )

    def _load_cached_auto_markdown(self) -> str:
        path = self._settings.resolved_data_dir() / "profile_auto.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def save_user_markdown(self, markdown: str) -> ProfileView:
        self._user_store.save(markdown)
        view = self.get_view()
        self._persist_display(view.markdown)
        return view

    def reset_user_markdown(self) -> ProfileView:
        self._user_store.clear()
        view = self.get_view()
        self._persist_display(view.markdown)
        return view

    def persist_after_sync(self) -> None:
        auto = self.build_auto()
        auto_path = self._settings.resolved_data_dir() / "profile_auto.md"
        auto_path.write_text(auto.markdown, encoding="utf-8")
        user = self._user_store.load()
        user_markdown = user.markdown.strip()
        display = user_markdown if user_markdown else auto.markdown
        self._persist_display(display)

    def _persist_display(self, markdown: str) -> None:
        profile_path = self._settings.resolved_data_dir() / "USER.md"
        profile_path.write_text(markdown, encoding="utf-8")
        workspace = KnowledgeWorkspace(self._settings.resolved_data_dir() / "workspace")
        workspace.update_profile_md(markdown)
