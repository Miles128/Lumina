"""Default skill/agent runners for WorkflowScheduler."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from secretary.agent.executable_skill import ExecutableSkillManager
from secretary.agent.llm_client import chat_completion
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import PendingConfirmation
from secretary.agent.turn_runner import AgentTurnPlan, TurnRunner
from secretary.services.file_auth import FileAuthService
from secretary.workflow.agent_tools import resolve_working_dir, tools_for_workflow_profile
from secretary.workflow.pause import WorkflowNodePaused
from secretary.workflow.scheduler import WorkflowRunError

logger = logging.getLogger(__name__)


class AgentRunner(Protocol):
    def __call__(
        self,
        prompt: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def resume(
        self,
        agent_state: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


def build_skill_runner(
    manager: ExecutableSkillManager,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
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


def _parse_agent_text(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return {"summary": ""}
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        logger.debug("agent node returned non-JSON text")
    return {"summary": cleaned}


def _pending_to_dict(pending: PendingConfirmation) -> dict[str, Any]:
    return {
        "action_id": pending.action_id,
        "tool_name": pending.tool_name,
        "arguments": dict(pending.arguments),
        "description": pending.description,
        "risk_level": pending.risk_level,
        "confirmation_kind": pending.confirmation_kind,
    }


def _pending_from_dict(raw: dict[str, Any]) -> PendingConfirmation:
    return PendingConfirmation(
        action_id=str(raw.get("action_id") or "workflow"),
        tool_name=str(raw.get("tool_name") or ""),
        arguments=dict(raw.get("arguments") or {}),
        description=str(raw.get("description") or ""),
        risk_level=str(raw.get("risk_level") or "medium"),
        confirmation_kind=str(raw.get("confirmation_kind") or "action"),
    )


def _loop_outputs(result: Any) -> dict[str, Any]:
    payload = _parse_agent_text(str(getattr(result, "reply", "") or ""))
    used = list(getattr(result, "used_tools", []) or [])
    if used:
        payload["used_tools"] = used
    payload["total_steps"] = int(getattr(result, "total_steps", 0) or 0)
    return payload


class WorkflowAgentRunner:
    """Dispatches mode=llm (single completion) vs mode=agent (AgentLoop)."""

    def __init__(
        self,
        llm_config: LlmConfig | None,
        *,
        turn_runner: TurnRunner | None = None,
        file_auth: FileAuthService | None = None,
        working_dir: Path | None = None,
    ) -> None:
        self._llm_config = llm_config
        self._turn_runner = turn_runner
        self._file_auth = file_auth
        self._working_dir = working_dir

    def __call__(
        self,
        prompt: str,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cfg = dict(config or {})
        mode = str(cfg.get("mode") or "llm").strip().lower()
        if mode == "agent":
            return self._run_agent_loop(prompt, inputs, cfg)
        return self._run_llm(prompt, inputs)

    def resume(
        self,
        agent_state: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not bool(payload.get("approved", True)):
            raise WorkflowRunError("tool confirmation rejected")
        if self._llm_config is None or self._turn_runner is None:
            raise WorkflowRunError("AgentLoop resume is not configured")
        pending_raw = dict(agent_state.get("pending") or {})
        messages = list(agent_state.get("messages") or [])
        if not pending_raw or not messages:
            raise WorkflowRunError("invalid agent_state for resume")
        profile = str(agent_state.get("profile") or "ask")
        max_steps = int(agent_state.get("max_steps") or 12)
        tools = tools_for_workflow_profile(profile, file_auth=self._file_auth)
        working_dir = resolve_working_dir(
            agent_state.get("working_dir"),
            self._working_dir,
        )
        pending = _pending_from_dict(pending_raw)
        result = self._turn_runner.run_confirmed_action(
            self._llm_config,
            tools,
            pending,
            messages,
            temperature=0.2,
            working_dir=working_dir,
        )
        if result.pending_confirmation and result.messages_snapshot is not None:
            raise WorkflowNodePaused(
                pause_prompt=result.pending_confirmation.description,
                pause_kind="tool_confirm",
                agent_state={
                    "messages": result.messages_snapshot,
                    "pending": _pending_to_dict(result.pending_confirmation),
                    "profile": profile,
                    "max_steps": max_steps,
                    "working_dir": str(working_dir) if working_dir else "",
                    "mode": "agent",
                },
            )
        return _loop_outputs(result)

    def _run_llm(self, prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if self._llm_config is None:
            raise WorkflowRunError("LLM is not configured for agent nodes")
        reply = chat_completion(
            self._llm_config,
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
        return _parse_agent_text(reply or "")

    def _run_agent_loop(
        self,
        prompt: str,
        inputs: dict[str, Any],
        cfg: dict[str, Any],
    ) -> dict[str, Any]:
        if self._llm_config is None:
            raise WorkflowRunError("LLM is not configured for agent nodes")
        if self._turn_runner is None:
            raise WorkflowRunError("TurnRunner is required for mode=agent")
        profile = str(cfg.get("profile") or "ask").strip().lower() or "ask"
        max_steps = int(cfg.get("max_steps") or (12 if profile in {"build", "auto"} else 8))
        tools = tools_for_workflow_profile(profile, file_auth=self._file_auth)
        working_dir = resolve_working_dir(cfg.get("working_dir"), self._working_dir)
        user_content = prompt
        if inputs:
            user_content = (
                f"{prompt}\n\nInputs JSON:\n{json.dumps(inputs, ensure_ascii=False)}"
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a workflow AgentLoop node inside Lumina. "
                    "Use tools when needed. Do not spawn sub-agents. "
                    "When finished, reply with the final result "
                    "(prefer a concise summary or JSON object)."
                ),
            },
            {"role": "user", "content": user_content},
        ]
        plan = AgentTurnPlan(messages=messages, max_steps=max_steps, tools=tools)
        result = self._turn_runner.run_agent_turn(
            self._llm_config,
            plan,
            temperature=0.2,
            working_dir=working_dir,
        )
        if result.pending_confirmation and result.messages_snapshot is not None:
            raise WorkflowNodePaused(
                pause_prompt=result.pending_confirmation.description,
                pause_kind="tool_confirm",
                agent_state={
                    "messages": result.messages_snapshot,
                    "pending": _pending_to_dict(result.pending_confirmation),
                    "profile": profile,
                    "max_steps": max_steps,
                    "working_dir": str(working_dir) if working_dir else "",
                    "mode": "agent",
                },
            )
        return _loop_outputs(result)


def build_agent_runner(
    llm_config: LlmConfig | None,
    *,
    turn_runner: TurnRunner | None = None,
    file_auth: FileAuthService | None = None,
    working_dir: Path | None = None,
) -> WorkflowAgentRunner:
    return WorkflowAgentRunner(
        llm_config,
        turn_runner=turn_runner,
        file_auth=file_auth,
        working_dir=working_dir,
    )
