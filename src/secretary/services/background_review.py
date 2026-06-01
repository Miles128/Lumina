"""Post-turn memory review (Hermes background_review pattern)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError
from secretary.memory.hermes_memory import HermesMemory
from secretary.services.memory_compress import MemoryCompressionService

if TYPE_CHECKING:
    from secretary.services.profile_service import ProfileService

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM = """你是记忆整理器。根据本轮对话，判断是否应更新持久记忆。
只输出 JSON：
{"action":"none"|"add"|"replace","target":"memory"|"user","text":"","old_text":"","reason":""}

规则：
- 用户明确说出的个人信息（姓名、职业、所在地、习惯、偏好、目标、家庭关系等）→ action=add, target=user
- 用户画像类稳定事实优先写入 target=user；任务/项目/环境类稳定事实 → target=memory
- 只记录稳定、可复用的事实，不要记临时闲聊、单次问答
- 不确定时 action=none
- replace/remove 需要 old_text 精确匹配现有内容片段
- text 用简洁中文陈述句，不要引号套话
"""


@dataclass(frozen=True)
class ReviewDecision:
    action: str
    target: str
    text: str
    old_text: str
    reason: str


class BackgroundReviewService:
    def __init__(
        self,
        hermes: HermesMemory,
        profile_service: ProfileService | None = None,
    ) -> None:
        self._hermes = hermes
        self._profile_service = profile_service
        self._compress = MemoryCompressionService(hermes)
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
            if decision.target == "user" and decision.action in {"add", "replace"}:
                self._sync_profile_fact(decision.text)
            logger.info("background review updated %s: %s", decision.target, decision.reason)
            self._compress.compress_if_needed(llm_config)
        except (AgentError, ValueError) as exc:
            logger.warning("background review skipped: %s", exc)
        finally:
            self._lock.release()

    def _sync_profile_fact(self, text: str) -> None:
        if self._profile_service is None:
            return
        try:
            self._profile_service.append_chat_fact(text)
        except OSError as exc:
            logger.warning("profile chat fact sync failed: %s", exc)

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
        if decision.target == "user" and decision.action in {"add", "replace"}:
            self._sync_profile_fact(decision.text)


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
