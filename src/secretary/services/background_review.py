"""Post-turn memory review (Hermes background_review pattern)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError
from secretary.memory.hermes_memory import HermesMemory

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM = """你是记忆整理器。根据本轮对话，判断是否应更新持久记忆。
只输出 JSON：
{"action":"none"|"add"|"replace","target":"memory"|"user","text":"","old_text":"","reason":""}
规则：
- 只记录稳定、可复用的事实（偏好、环境、长期目标），不要记临时闲聊
- 不确定时 action=none
- replace/remove 需要 old_text 精确匹配现有内容片段
"""


@dataclass(frozen=True)
class ReviewDecision:
    action: str
    target: str
    text: str
    old_text: str
    reason: str


class BackgroundReviewService:
    def __init__(self, hermes: HermesMemory) -> None:
        self._hermes = hermes
        self._lock = threading.Lock()

    def schedule(self, user_message: str, assistant_reply: str, llm_config: LlmConfig | None) -> None:
        if llm_config is None:
            return
        cleaned_user = user_message.strip()
        cleaned_reply = assistant_reply.strip()
        if not cleaned_user or not cleaned_reply:
            return
        thread = threading.Thread(
            target=self._run_review,
            args=(cleaned_user, cleaned_reply, llm_config),
            daemon=True,
            name="lumina-background-review",
        )
        thread.start()

    def _run_review(self, user_message: str, assistant_reply: str, llm_config: LlmConfig) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            decision = self._classify(user_message, assistant_reply, llm_config)
            if decision.action == "none":
                return
            self._hermes.mutate_memory(
                decision.action,
                decision.target,
                text=decision.text,
                old_text=decision.old_text,
            )
            logger.info("background review updated %s: %s", decision.target, decision.reason)
        except (AgentError, ValueError) as exc:
            logger.warning("background review skipped: %s", exc)
        finally:
            self._lock.release()

    def _classify(
        self,
        user_message: str,
        assistant_reply: str,
        llm_config: LlmConfig,
    ) -> ReviewDecision:
        snapshot = self._hermes.prompt_snapshot() or "(empty)"
        raw = chat_completion(
            llm_config,
            [
                {"role": "system", "content": _REVIEW_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Current memory snapshot:\n{snapshot}\n\n"
                        f"User: {user_message}\n\nAssistant: {assistant_reply}"
                    ),
                },
            ],
            temperature=0.0,
            timeout=45.0,
        )
        return _parse_review_json(raw)

    def apply_decision_for_tests(self, decision: ReviewDecision) -> None:
        if decision.action == "none":
            return
        self._hermes.mutate_memory(
            decision.action,
            decision.target,
            text=decision.text,
            old_text=decision.old_text,
        )


def _parse_review_json(raw: str) -> ReviewDecision:
    import json

    cleaned = raw.strip()
    fence = re_search_json_fence(cleaned)
    if fence:
        cleaned = fence
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise AgentError("background review returned invalid JSON")
    action = str(payload.get("action", "none")).strip().lower()
    target = str(payload.get("target", "memory")).strip().lower()
    if action not in {"none", "add", "replace", "remove"}:
        action = "none"
    if target not in {"memory", "user"}:
        target = "memory"
    return ReviewDecision(
        action=action,
        target=target,
        text=str(payload.get("text", "")),
        old_text=str(payload.get("old_text", "")),
        reason=str(payload.get("reason", "")),
    )


def re_search_json_fence(cleaned: str) -> str | None:
    import re

    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if match:
        return match.group(1).strip()
    return None
