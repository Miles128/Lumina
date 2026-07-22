"""Default skill/agent runners for WorkflowScheduler."""

from __future__ import annotations

import json
import logging
from typing import Any

from secretary.agent.executable_skill import ExecutableSkillManager
from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.workflow.scheduler import WorkflowRunError

logger = logging.getLogger(__name__)


def build_skill_runner(manager: ExecutableSkillManager):
    def skill_runner(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        skill = manager.get_skill(name)
        if skill is None or not skill.is_executable:
            raise WorkflowRunError(f"executable skill not found: {name}")
        result = skill.execute(dict(inputs))
        if not result.success:
            raise RuntimeError(result.error or f"skill {name} failed")
        raw = (result.output or "").strip()
        if not raw or raw == "(no output)":
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"output": parsed}
        except json.JSONDecodeError:
            return {"output": raw}

    return skill_runner


def build_agent_runner(llm_config: LlmConfig | None):
    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if llm_config is None:
            raise WorkflowRunError("LLM is not configured for agent nodes")
        reply = chat_completion(
            llm_config,
            [
                {
                    "role": "system",
                    "content": (
                        "You are a workflow agent node. Reply with the result only. "
                        "If JSON is requested, return valid JSON object text."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt
                    if not inputs
                    else f"{prompt}\n\nInputs JSON:\n{json.dumps(inputs, ensure_ascii=False)}",
                },
            ],
            temperature=0.2,
        )
        text = (reply or "").strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            logger.debug("agent node returned non-JSON text")
        return {"summary": text}

    return agent_runner
