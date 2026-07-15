"""F21 Reflexion: spawn reflect sub-agent to generate structured reflection.

Wraps SubAgentRunner.run_from_tool with archetype="reflect".
Parses JSON output; returns empty string on any failure (never crashes main flow).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from secretary.agent.reflection.trigger import FailureSignal
from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.runner import SubAgentDeps, SubAgentRunner

logger = logging.getLogger(__name__)

# Extract first JSON object from text (reflector may wrap JSON in prose)
_JSON_EXTRACT = re.compile(r"\{[^{}]*\}", re.DOTALL)


class ReflectionRunner:
    """Spawns a reflect sub-agent and parses its JSON output."""

    def __init__(
        self,
        *,
        llm_config: Any,
        file_auth: Any,
        memory_store: Any,
        memory: Any,
        lumina_dir: Path | None = None,
    ) -> None:
        deps = SubAgentDeps(
            llm_config=llm_config,
            file_auth=file_auth,
            memory_store=memory_store,
            memory=memory,
            lumina_dir=lumina_dir,
            temperature=0.3,
        )
        self._runner = SubAgentRunner(deps)

    def run(
        self,
        signal: FailureSignal,
        *,
        working_dir: Path,
        parent_session_id: str = "",
    ) -> str:
        """Spawn reflect sub-agent. Returns JSON string, or "" on failure."""
        context = self._build_context(signal)
        goal = f"分析失败 turn: mode={signal.mode}, summary={signal.summary}"

        spawn_context = SpawnContext(parent_session_id=parent_session_id)
        try:
            output = self._runner.run_from_tool(
                {
                    "goal": goal,
                    "context": context,
                    "archetype": "reflect",
                },
                spawn_context,
                working_dir,
                progress_callback=None,
                cancel_check=None,
            )
        except Exception as exc:
            logger.warning("Reflection sub-agent failed: %s", exc)
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
