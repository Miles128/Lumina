"""Periodic background think — review memory and recent context without user prompt."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import resolve_llm_config
from secretary.config import Settings
from secretary.exceptions import AgentError
from secretary.memory.lumina_memory import LuminaMemory
from secretary.services.agent_config import AgentConfigStore
from secretary.services.background_review import re_search_json_fence
from secretary.services.profile_service import ProfileService

logger = logging.getLogger(__name__)

_STATE_FILE = "think_state.json"

_THINK_SYSTEM = """你是灵犀的后台思考模块。根据记忆、用户画像和最近对话，提炼值得长期保留的信息。
只输出 JSON：
{"insights":["..."], "updates":[{"action":"none"|"add"|"replace","target":"memory"|"user","text":"","old_text":""}]}
规则：
- 只记录稳定、可复用的事实，不要猜测
- 没有值得更新的内容时 updates 为空数组
- 不确定时 action=none
"""


class ScheduledThinkService:
    def __init__(
        self,
        settings: Settings,
        hermes: LuminaMemory,
        profile_service: ProfileService,
        agent_config_store: AgentConfigStore,
    ) -> None:
        self._settings = settings
        self._hermes = hermes
        self._profile_service = profile_service
        self._agent_config_store = agent_config_store
        self._state_path = settings.resolved_data_dir() / _STATE_FILE

    def should_run(self) -> bool:
        if not self._settings.think_enabled:
            return False
        last = self._load_state().get("last_run_at", "")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(str(last))
        except ValueError:
            return True
        elapsed_hours = (datetime.now(UTC) - last_dt.replace(tzinfo=UTC)).total_seconds() / 3600
        return elapsed_hours >= max(self._settings.think_interval_hours, 1)

    def run(self) -> str:
        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        if llm_config is None:
            raise AgentError("未配置大模型，无法进行后台思考")

        profile = self._profile_service.get_view().markdown[:1200]
        memory = self._hermes.prompt_snapshot() or ""
        if not profile.strip() and not memory.strip():
            from secretary.memory.db import MemoryStore

            store = MemoryStore(self._settings.resolved_data_dir() / "memory.db")
            if sum(store.count_by_source().values()) == 0:
                logger.info("think skipped: no synced profile or memory yet")
                self._save_state("## 后台思考\n\n- 跳过：尚无同步数据，请先同步。")
                return "skipped: no synced data"

        memory = memory or "(empty)"
        recent = self._hermes.recent_session_messages(limit=30)
        recent_text = "\n".join(
            f"[{item['role']}] {item['content'][:200]}"
            for item in recent
        ) or "(no recent messages)"

        raw = chat_completion(
            llm_config,
            [
                {"role": "system", "content": _THINK_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Profile:\n{profile}\n\nMemory:\n{memory}\n\nRecent:\n{recent_text}"
                    ),
                },
            ],
            temperature=0.2,
            timeout=90.0,
        )
        insights, applied = self._apply_result(raw)
        markdown = self._format_report(insights, applied)
        self._save_state(markdown)
        logger.info("scheduled think complete, applied=%s", applied)
        return markdown

    @staticmethod
    def load_latest(data_dir: Path) -> dict[str, str] | None:
        path = data_dir / _STATE_FILE
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        markdown = payload.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            return None
        return {
            "markdown": markdown,
            "last_run_at": str(payload.get("last_run_at", "")),
        }

    def _apply_result(self, raw: str) -> tuple[list[str], int]:
        cleaned = raw.strip()
        fence = re_search_json_fence(cleaned)
        if fence:
            cleaned = fence
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise AgentError("后台思考返回格式无效")
        insights = [str(item) for item in payload.get("insights", []) if str(item).strip()]
        updates = payload.get("updates", [])
        applied = 0
        if isinstance(updates, list):
            for item in updates:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action", "none")).strip().lower()
                if action == "none":
                    continue
                target = str(item.get("target", "memory")).strip().lower()
                if target not in {"memory", "user"}:
                    target = "memory"
                self._hermes.mutate_memory(
                    action,
                    target,
                    text=str(item.get("text", "")),
                    old_text=str(item.get("old_text", "")),
                )
                applied += 1
        return insights, applied

    def _format_report(self, insights: list[str], applied: int) -> str:
        lines = ["## 后台思考", f"- 时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"]
        if insights:
            lines.append("- 洞察：")
            lines.extend(f"  - {item}" for item in insights[:8])
        lines.append(f"- 记忆更新：{applied} 条")
        return "\n".join(lines)

    def _load_state(self) -> dict[str, object]:
        if not self._state_path.exists():
            return {}
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, markdown: str) -> None:
        payload = {
            "last_run_at": datetime.now(UTC).isoformat(),
            "markdown": markdown,
        }
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
