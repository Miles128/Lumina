"""Parent-agent tool that spawns read-only explore sub-agents."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from secretary.agent.progress_events import ProgressEvent
from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.resume import SubAgentResumeState
from secretary.agent.subagent.runner import SubAgentDeps, SubAgentRunner
from secretary.agent.tools.base import Tool


class SpawnSubagentTool(Tool):
    name = "spawn_subagent"
    description = (
        "Delegate a focused sub-task to an isolated sub-agent. "
        "Returns a summary only; intermediate steps stay private. "
        "Archetypes: explore (read-only), worker (read/write), verify (review), plan (read-only planning). "
        "Optional goals[] runs up to 3 explore tasks in parallel (Hermes batch)."
    )
    needs_confirmation = False
    risk_level = "low"

    def __init__(
        self,
        deps: SubAgentDeps,
        spawn_context: SpawnContext,
    ) -> None:
        self._spawn_context = spawn_context
        self._progress_callback: Callable[[ProgressEvent], None] | None = None
        self._paused: SubAgentResumeState | None = None
        self._runner = SubAgentRunner(deps, on_paused=self._store_paused)

    def _store_paused(self, state: SubAgentResumeState) -> None:
        self._paused = state

    def consume_paused(self) -> SubAgentResumeState | None:
        state = self._paused
        self._paused = None
        return state

    def bind_progress(self, callback: Callable[[ProgressEvent], None] | None) -> None:
        self._progress_callback = callback

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Clear, self-contained task for the sub-agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional paths, constraints, or facts the sub-agent needs.",
                },
                "archetype": {
                    "type": "string",
                    "description": "explore | worker | verify | plan, or a custom name from ~/.lumina/subagents/*.md",
                },
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                    "description": "Optional: 2–3 explore goals run in parallel (omit goal when set).",
                },
            },
            "required": [],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return self._runner.run_from_tool(
            arguments,
            self._spawn_context,
            working_dir,
            progress_callback=self._progress_callback,
        )

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        goal = str(arguments.get("goal", "")).strip()
        archetype = str(arguments.get("archetype", "explore")).strip() or "explore"
        preview = goal[:80] + ("…" if len(goal) > 80 else "")
        return f"委派子任务 ({archetype})：{preview}"
