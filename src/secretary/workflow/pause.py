"""Pause signals for workflow node execution (HumanReview / tool confirm)."""

from __future__ import annotations

from typing import Any


class WorkflowNodePaused(Exception):
    """Raised by agent runners when a node must wait for human input."""

    def __init__(
        self,
        *,
        pause_prompt: str,
        pause_kind: str,
        agent_state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(pause_prompt)
        self.pause_prompt = pause_prompt
        self.pause_kind = pause_kind  # human_review | confirm | tool_confirm
        self.agent_state = dict(agent_state or {})
