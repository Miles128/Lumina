"""Daily briefing generation from local memory / Shibei — no platform connectors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig, resolve_llm_config
from secretary.config import Settings
from secretary.exceptions import AgentError
from secretary.memory.db import MemoryStore
from secretary.services.agent_config import AgentConfigStore
from secretary.services.profile_service import ProfileService

if TYPE_CHECKING:
    from secretary.services.shibei_service import ShibeiService

_BRIEFING_QUERIES: dict[str, str] = {
    "agenda": "日程 待办 任务 会议 今日",
    "notes": "笔记 阅读 书摘 划线 近期",
}


class BriefingService:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        shibei_service: ShibeiService | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._shibei = shibei_service
        self._agent_config_store = AgentConfigStore(settings.resolved_data_dir() / "agent.json")

    def generate(self, profile_service: ProfileService) -> str:
        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        context = self._build_context(profile_service)
        if llm_config is not None:
            try:
                return self._generate_with_llm(context, llm_config)
            except AgentError:
                pass
        return self._generate_rule_based(context)

    def _search_via_shibei(self, query: str) -> str | None:
        if self._shibei is None or not self._shibei.is_enabled() or not self._shibei.is_available():
            return None
        try:
            result = self._shibei.search(query, limit=5)
        except Exception:
            return None
        if not result.strip() or result.startswith("Error:"):
            return None
        return result

    def _build_context(self, profile_service: ProfileService) -> dict[str, str]:
        view = profile_service.get_view()
        agenda_text = self._fetch_section("agenda")
        notes_text = self._fetch_section("notes")
        empty_hint = ""
        if agenda_text == notes_text == "暂无":
            empty_hint = (
                "> 提示：本地知识库暂无足够材料。"
                "可在设置中配置 Shibei 知识库并导入笔记后再生成简报。\n\n"
            )
        return {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "profile_excerpt": view.markdown[:1200],
            "agenda": agenda_text,
            "notes": notes_text,
            "empty_hint": empty_hint,
        }

    def _fetch_section(self, key: str) -> str:
        query = _BRIEFING_QUERIES.get(key, "")
        if query:
            shibei_result = self._search_via_shibei(query)
            if shibei_result is not None:
                return shibei_result
        hits = self._store.search(query, limit=5) if query else []
        lines: list[str] = []
        for chunk in hits:
            title = getattr(chunk, "title", "")
            if isinstance(title, str) and title.strip():
                lines.append(f"- {title.strip()}")
        return "\n".join(lines) if lines else "暂无"

    def _generate_with_llm(self, context: dict[str, str], llm_config: LlmConfig) -> str:
        prompt = (
            f"今天是 {context['date']}。根据以下本地知识，写一份简洁的中文早报（markdown），"
            "包含：今日关注、待办与日程线索、阅读与笔记摘要。只使用给定事实，不要编造。\n\n"
            f"{context['empty_hint']}"
            f"## 持久记忆摘录\n{context['profile_excerpt']}\n\n"
            f"## 日程与待办线索\n{context['agenda']}\n\n"
            f"## 阅读与笔记\n{context['notes']}"
        )
        body = chat_completion(
            llm_config,
            [
                {"role": "system", "content": "你是本地 Agent 助手，负责写每日简报。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return (
            f"# 今日简报\n\n"
            f"> 生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"{body.strip()}\n"
        )

    def _generate_rule_based(self, context: dict[str, str]) -> str:
        return (
            f"# 今日简报\n\n"
            f"> 生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"{context['empty_hint']}"
            f"## 日程与待办线索\n{context['agenda']}\n\n"
            f"## 阅读与笔记\n{context['notes']}\n\n"
            f"## 持久记忆摘录\n{context['profile_excerpt'][:800]}\n"
        )
