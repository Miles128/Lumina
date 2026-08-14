"""F21 Reflexion: analyze a failed turn into a structured lesson.

Runs a single llm_client completion (no tool loop) against the reflect system
prompt; parses JSON output; returns empty string on any failure (never crashes
the main flow).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from secretary.agent.llm_client import chat_completion
from secretary.agent.reflection.trigger import FailureSignal
from secretary.agent.subagent.registry import REFLECT_PROMPT

logger = logging.getLogger(__name__)

# Extract first JSON object from text (reflector may wrap JSON in prose)
_JSON_EXTRACT = re.compile(r"\{[^{}]*\}", re.DOTALL)


class ReflectionRunner:
    """Runs the reflect prompt and parses its JSON output."""

    def __init__(
        self,
        *,
        llm_config: Any,
        file_auth: Any,
        memory_store: Any,
        memory: Any,
        lumina_dir: Path | None = None,
    ) -> None:
        # file_auth / memory_store / memory / lumina_dir are kept for signature
        # compatibility with ChatService._ensure_reflection_runner; the pure
        # completion path below does not need tools.
        self._llm_config = llm_config

    def run(
        self,
        signal: FailureSignal,
        *,
        working_dir: Path,
        parent_session_id: str = "",
    ) -> str:
        """Analyze a failure signal. Returns JSON string, or "" on failure."""
        context = self._build_context(signal)
        goal = f"分析失败 turn: mode={signal.mode}, summary={signal.summary}"

        messages = [
            {"role": "system", "content": REFLECT_PROMPT},
            {"role": "user", "content": f"## Task\n{goal}\n\n## Context\n{context}"},
        ]
        try:
            output = chat_completion(
                self._llm_config,
                messages,
                temperature=0.3,
                thinking="disabled",
            )
        except Exception as exc:
            logger.warning("Reflection completion failed: %s", exc)
            return ""

        return self._extract_json(output)

    def _build_context(self, signal: FailureSignal) -> str:
        """Build context string for the reflector."""
        parts = [
            f"failure_mode: {signal.mode}",
            f"summary: {signal.summary}",
            f"user_message: {signal.user_message}",
            f"raw_reply: {signal.raw_reply}",
            f"tool_calls_summary: {json.dumps(signal.tool_calls_summary, ensure_ascii=False)}",
        ]
        if signal.verify_issues:
            parts.append(f"verify_issues: {signal.verify_issues}")
        return "\n".join(parts)

    @staticmethod
    def _extract_json(output: str) -> str:
        """Extract the first JSON object from reflector output."""
        if not output or output.startswith("Error:"):
            return ""
        match = _JSON_EXTRACT.search(output)
        if match is None:
            logger.warning("No JSON found in reflector output: %s", output[:200])
            return ""
        try:
            json.loads(match.group())
            return match.group()
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in reflector output: %s", output[:200])
            return ""
