"""Periodic session memory summarization into durable MEMORY.md."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig, resolve_llm_config
from secretary.config import Settings
from secretary.exceptions import AgentError
from secretary.memory.hermes_memory import HermesMemory
from secretary.services.agent_config import AgentConfigStore

logger = logging.getLogger(__name__)

_STATE_FILE = "memory_summary_state.json"
_SUMMARY_HEADER = "## 会话摘要"

_SUMMARY_SYSTEM = """你是记忆摘要助手。根据最近对话记录，写一段简洁中文摘要（150-400字）。
只保留稳定事实、未完成事项、重要结论。不要编造。不要输出 JSON，直接输出摘要正文。"""


class MemorySummarizerService:
    def __init__(
        self,
        settings: Settings,
        hermes: HermesMemory,
        agent_config_store: AgentConfigStore,
    ) -> None:
        self._settings = settings
        self._hermes = hermes
        self._agent_config_store = agent_config_store
        self._state_path = settings.resolved_data_dir() / _STATE_FILE

    def should_run(self, hour: int) -> bool:
        if not self._settings.memory_summary_enabled:
            return False
        if hour != self._settings.memory_summary_hour:
            return False
        today = datetime.now().date().isoformat()
        return self._load_state().get("last_summary_date") != today

    def run(self) -> str:
        llm_config = resolve_llm_config(self._settings, self._agent_config_store)
        if llm_config is None:
            raise AgentError("未配置大模型，无法生成记忆摘要")

        recent = self._hermes.recent_session_messages(limit=60)
        if not recent:
            summary = "暂无近期对话，跳过摘要。"
            self._save_state(summary)
            return summary

        transcript = "\n".join(
            f"[{item['timestamp'][:16]}][{item['role']}] {item['content'][:300]}"
            for item in recent
        )
        summary = chat_completion(
            llm_config,
            [
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": f"Recent conversations:\n{transcript}"},
            ],
            temperature=0.2,
            timeout=90.0,
        ).strip()
        if not summary:
            raise AgentError("记忆摘要生成为空")

        self._upsert_memory_summary(summary)
        self._save_state(summary)
        logger.info("memory summary generated (%s chars)", len(summary))
        return summary

    @staticmethod
    def load_latest(data_dir: Path) -> dict[str, str] | None:
        path = data_dir / _STATE_FILE
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        return {
            "summary": summary,
            "last_summary_date": str(payload.get("last_summary_date", "")),
            "generated_at": str(payload.get("generated_at", "")),
        }

    def _upsert_memory_summary(self, summary: str) -> None:
        current = self._hermes.read_memory_md()
        block = f"{_SUMMARY_HEADER}\n\n{summary.strip()}\n"
        if _SUMMARY_HEADER in current:
            updated = re.sub(
                rf"{re.escape(_SUMMARY_HEADER)}[\s\S]*?(?=\n## |\Z)",
                block.rstrip() + "\n\n",
                current,
                count=1,
            )
        else:
            updated = (block + "\n" + current).strip() + "\n"
        self._hermes.write_memory_md(updated[:8000])

    def _load_state(self) -> dict[str, object]:
        if not self._state_path.exists():
            return {}
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, summary: str) -> None:
        payload = {
            "last_summary_date": datetime.now().date().isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": summary,
        }
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
