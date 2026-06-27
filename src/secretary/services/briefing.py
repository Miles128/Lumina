"""Daily briefing generation."""

from __future__ import annotations

from datetime import UTC, datetime

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig, resolve_llm_config
from secretary.config import Settings
from secretary.core.types import SourceKind
from secretary.exceptions import AgentError
from secretary.memory.db import MemoryStore
from secretary.services.agent_config import AgentConfigStore
from secretary.services.profile_service import ProfileService


class BriefingService:
    def __init__(self, settings: Settings, store: MemoryStore) -> None:
        self._settings = settings
        self._store = store
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

    def _build_context(self, profile_service: ProfileService) -> dict[str, str]:
        view = profile_service.get_view()
        feishu = self._store.list_by_source(SourceKind.FEISHU, limit=8)
        email = self._store.list_by_source(SourceKind.EMAIL, limit=5)
        weread = self._store.list_by_source(SourceKind.WEREAD, limit=5)

        from collections.abc import Sequence

        def titles(chunks: Sequence[object]) -> str:
            lines: list[str] = []
            for chunk in chunks:
                title = getattr(chunk, "title", "")
                if isinstance(title, str) and title.strip():
                    lines.append(f"- {title.strip()}")
            return "\n".join(lines) if lines else "暂无"

        feishu_text = titles(feishu)
        email_text = titles(email)
        weread_text = titles(weread)
        sync_hint = ""
        if feishu_text == email_text == weread_text == "暂无":
            sync_hint = (
                "> 提示：本地尚无飞书/邮箱/读书等同步数据。"
                "请先在灵犀右上角点击「同步」。\n\n"
            )

        return {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "profile_excerpt": view.markdown[:1200],
            "feishu": feishu_text,
            "email": email_text,
            "weread": weread_text,
            "sync_hint": sync_hint,
        }

    def _generate_with_llm(self, context: dict[str, str], llm_config: LlmConfig) -> str:
        prompt = (
            f"今天是 {context['date']}。根据以下本地同步数据，写一份简洁的中文早报（markdown），"
            "包含：今日关注、日程与待办、阅读与信息摘要。只使用给定事实，不要编造。\n\n"
            f"{context['sync_hint']}"
            f"## 画像摘录\n{context['profile_excerpt']}\n\n"
            f"## 飞书\n{context['feishu']}\n\n"
            f"## 邮箱\n{context['email']}\n\n"
            f"## 阅读\n{context['weread']}"
        )
        body = chat_completion(
            llm_config,
            [
                {"role": "system", "content": "你是个人 AI 秘书，负责写每日简报。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return f"# 今日简报\n\n> 生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n{body.strip()}\n"

    def _generate_rule_based(self, context: dict[str, str]) -> str:
        return (
            f"# 今日简报\n\n"
            f"> 生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"{context['sync_hint']}"
            f"## 飞书\n{context['feishu']}\n\n"
            f"## 邮箱\n{context['email']}\n\n"
            f"## 阅读\n{context['weread']}\n\n"
            f"## 画像摘录\n{context['profile_excerpt'][:800]}\n"
        )
