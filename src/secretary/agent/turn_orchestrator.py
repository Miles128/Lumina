"""Execution orchestrator for agent tool loops."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, LoopResult
from secretary.agent.tools.base import Tool
from secretary.agent.progress_events import ProgressEvent
from secretary.services.file_auth import FileAuthService

if TYPE_CHECKING:
    from secretary.agent.mcp_manager import McpManager


@dataclass(frozen=True)
class AgentTurnPlan:
    """Prepared inputs for one agent loop turn."""

    messages: list[dict[str, str]]
    max_steps: int
    tools: list[Tool]


class TurnOrchestrator:
    """Thin orchestration layer around AgentLoop execution."""

    def __init__(self, file_auth: FileAuthService) -> None:
        self._file_auth = file_auth

    def run_agent_turn(
        self,
        llm_config: LlmConfig,
        plan: AgentTurnPlan,
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> LoopResult:
        loop = AgentLoop(
            llm_config,
            tools=plan.tools,
            max_steps=plan.max_steps,
            file_auth=self._file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
        )
        return loop.run(plan.messages, temperature=temperature)

    def run_confirmed_action(
        self,
        llm_config: LlmConfig,
        tools: list[Tool],
        pending: Any,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        working_dir: Path | None = None,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> LoopResult:
        loop = AgentLoop(
            llm_config,
            tools=tools,
            max_steps=8,
            file_auth=self._file_auth,
            progress_callback=progress_callback,
            working_dir=working_dir,
        )
        return loop.execute_confirmed(pending, messages, temperature=temperature)

