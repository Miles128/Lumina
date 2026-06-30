"""Semantic compression for durable MEMORY.md / USER.md when near size limits."""

from __future__ import annotations

import logging
from collections.abc import Callable

from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError
from secretary.memory.lumina_memory import (
    MEMORY_MD_MAX_CHARS,
    USER_MD_MAX_CHARS,
    LuminaMemory,
)

logger = logging.getLogger(__name__)

_COMPRESS_THRESHOLD = 0.88

_COMPRESS_SYSTEM = """你是持久记忆压缩器。将下面的记忆文本压缩到更短，但必须保留所有稳定、可复用的事实。
要求：
- 删除重复、近义冗余、过时临时信息
- 保留用户个人信息、偏好、长期目标、重要结论
- 输出长度不超过 {max_chars} 个字符（中文按字计）
- 直接输出压缩后的全文，不要解释、不要 JSON"""


class MemoryCompressionService:
    def __init__(self, memory: LuminaMemory) -> None:
        self._memory = memory

    def compress_if_needed(self, llm_config: LlmConfig | None) -> bool:
        if llm_config is None:
            return False
        changed = False
        changed |= self._compress_target(
            llm_config,
            read=self._memory.read_memory_md,
            write=self._memory.write_memory_md,
            max_chars=MEMORY_MD_MAX_CHARS,
            label="MEMORY.md",
        )
        changed |= self._compress_target(
            llm_config,
            read=self._memory.read_user_md,
            write=self._memory.write_user_md,
            max_chars=USER_MD_MAX_CHARS,
            label="USER.md",
        )
        return changed

    def _compress_target(
        self,
        llm_config: LlmConfig,
        *,
        read: Callable[[], str],
        write: Callable[[str], None],
        max_chars: int,
        label: str,
    ) -> bool:
        content = read().strip()
        if not content:
            return False
        threshold = int(max_chars * _COMPRESS_THRESHOLD)
        if len(content) <= threshold:
            return False
        try:
            compressed = chat_completion(
                llm_config,
                [
                    {
                        "role": "system",
                        "content": _COMPRESS_SYSTEM.format(max_chars=max_chars),
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.0,
                timeout=60.0,
            ).strip()
        except AgentError as exc:
            logger.warning("memory compress skipped for %s: %s", label, exc)
            return False
        if not compressed or len(compressed) >= len(content):
            return False
        write(compressed)
        logger.info("compressed %s: %s -> %s chars", label, len(content), len(compressed))
        return True
