"""Pause/resume state for sub-agent runs (Codex turn-approve semantics)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import PendingConfirmation, StepResult
from secretary.agent.tools.base import Tool


@dataclass
class ParentTurnResumeState:
    """Resume parent AgentLoop after a paused sub-agent completes."""

    messages_snapshot: list[dict[str, Any]]
    tools: list[Tool]
    max_steps: int
    pending_step: StepResult
    assistant_message: dict[str, Any] | None
    native_used: bool
    step_idx: int
    llm_config: LlmConfig
    session_id: str
    user_message: str
    profile_excerpt: str
    memory_hits: int


@dataclass
class SubAgentResumeState:
    """Everything needed to resume a paused child AgentLoop after user confirm."""

    run_id: str
    archetype: str
    goal: str
    context: str
    child_session_id: str
    parent_session_id: str
    messages: list[dict[str, Any]]
    max_steps: int
    working_dir: Path
    pending: PendingConfirmation
    llm_config: LlmConfig
    temperature: float
    success_criteria: str = ""
    pending_step: StepResult | None = None
    steps_completed: int = 0
    used_tools: list[str] = field(default_factory=list)
