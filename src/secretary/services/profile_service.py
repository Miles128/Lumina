"""Merge auto profile with user edits."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from secretary.agent.llm_config import resolve_llm_config
from secretary.config import Settings
from secretary.core.types import UserProfile
from secretary.memory.db import MemoryStore
from secretary.memory.kb import KnowledgeWorkspace
from secretary.memory.profile import ProfileBuilder
from secretary.services.agent_config import AgentConfigStore
from secretary.services.local_documents_profiler import LocalDocumentsProfiler
from secretary.services.user_profile_store import UserProfileStore


class ProfileView(BaseModel):
    generated_at: datetime
    markdown: str
    auto_markdown: str
    user_markdown: str
    chat_facts_markdown: str = ""
    is_user_edited: bool
    sections: list[dict[str, str | int]] = Field(default_factory=list)


_CHAT_FACTS_HEADER = "## 对话中了解到的信息"
_CHAT_FACTS_PATH_NAME = "profile_chat_facts.md"


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
        chat_facts = self._load_chat_facts_markdown()
        if chat_facts and _CHAT_FACTS_HEADER not in display:
            display = f"{display.rstrip()}\n\n{chat_facts}".strip()
        return ProfileView(
            generated_at=rule_auto.generated_at,
            markdown=display,
            auto_markdown=auto_markdown,
            user_markdown=user_markdown,
            chat_facts_markdown=chat_facts,
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
        self._user_store.save(self._strip_chat_facts(markdown))
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
        chat_facts = self._load_chat_facts_markdown()
        if chat_facts:
            display = f"{display.rstrip()}\n\n{chat_facts}".strip()
        self._persist_display(display)

    def append_chat_fact(self, fact: str) -> None:
        """Merge a chat-derived personal fact into profile display."""
        line = fact.strip()
        if not line:
            return
        path = self._chat_facts_path()
        existing = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        bullet = f"- {line}"
        if bullet in existing:
            return
        if not existing:
            updated = f"{_CHAT_FACTS_HEADER}\n\n{bullet}"
        else:
            updated = f"{existing}\n{bullet}"
        path.write_text(updated.strip() + "\n", encoding="utf-8")
        view = self.get_view()
        self._persist_display(view.markdown)

    def _chat_facts_path(self) -> Path:
        return self._settings.resolved_data_dir() / _CHAT_FACTS_PATH_NAME

    def _load_chat_facts_markdown(self) -> str:
        path = self._chat_facts_path()
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _strip_chat_facts(self, markdown: str) -> str:
        header = _CHAT_FACTS_HEADER
        idx = markdown.find(header)
        if idx >= 0:
            return markdown[:idx].rstrip()
        return markdown.strip()

    def clear_chat_derived_facts(self) -> ProfileView:
        """Remove profile bullets inferred from chat (may include assistant hallucinations)."""
        path = self._chat_facts_path()
        if path.exists():
            path.unlink()
        view = self.get_view()
        auto = self._load_cached_auto_markdown()
        user = self._user_store.load()
        user_markdown = user.markdown.strip()
        display = user_markdown if user_markdown else (auto or view.auto_markdown)
        self._persist_display(display)
        return self.get_view()

    def _persist_display(self, markdown: str) -> None:
        profile_path = self._settings.resolved_data_dir() / "USER.md"
        profile_path.write_text(markdown, encoding="utf-8")
        workspace = KnowledgeWorkspace(self._settings.resolved_data_dir() / "workspace")
        workspace.update_profile_md(markdown)


def clear_polluted_derived_state(data_dir: Path) -> list[str]:
    """Drop scheduler files that may embed hallucinated chat summaries."""
    removed: list[str] = []
    for name in ("think_state.json", "memory_summary_state.json"):
        path = data_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)
    return removed
