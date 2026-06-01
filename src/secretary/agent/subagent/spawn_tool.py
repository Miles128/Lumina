"""Parent-agent tool that spawns read-only explore sub-agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from secretary.agent.loop import Tool
from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.runner import SubAgentRunner


class SpawnSubagentTool(Tool):
    name = "spawn_subagent"
    description = (
        "Delegate a focused sub-task to an isolated read-only sub-agent. "
        "Returns a summary only; intermediate steps stay private. "
        "Use archetype 'explore' for codebase/memory/web research."
    )
    needs_confirmation = False
    risk_level = "low"

    def __init__(
        self,
        runner: SubAgentRunner,
        spawn_context: SpawnContext,
    ) -> None:
        self._runner = runner
        self._spawn_context = spawn_context
        self._progress_callback = None

    def bind_progress(self, callback) -> None:
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
                    "enum": ["explore"],
                    "description": "Sub-agent type. Phase 1 supports read-only 'explore' only.",
                },
            },
            "required": ["goal"],
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
