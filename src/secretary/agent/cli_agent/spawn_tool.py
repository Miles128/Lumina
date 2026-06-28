"""Parent-agent tool that delegates to external CLI agents (FR-30)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from secretary.agent.cli_agent.runner import CliAgentRunner
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.tools.base import Tool


class SpawnCliAgentTool(Tool):
    name = "spawn_cli_agent"
    description = (
        "Delegate a heavy task to an external CLI agent (codex, claude, opencode). "
        "Returns a final summary only; CLI stdout does not enter the main context. "
        "Requires user confirmation before running."
    )
    needs_confirmation = True
    risk_level = "high"

    def __init__(self, runner: CliAgentRunner, *, default_cwd: Path) -> None:
        self._runner = runner
        self._default_cwd = default_cwd
        self._progress_callback: Callable[[ProgressEvent], None] | None = None

    def bind_progress(self, callback: Callable[[ProgressEvent], None] | None) -> None:
        self._progress_callback = callback

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Provider name from ~/.lumina/cli-agents.json (e.g. codex, claude).",
                },
                "goal": {
                    "type": "string",
                    "description": "Self-contained task for the CLI agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional constraints, paths, or facts.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (default: shell_working_dir).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (capped by provider config).",
                },
            },
            "required": ["goal"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        cwd = self._default_cwd if self._default_cwd.is_dir() else working_dir
        return self._runner.run_from_tool(
            arguments,
            cwd,
            progress_callback=self._progress_callback,
        )

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        provider = str(arguments.get("provider", "")).strip() or "codex"
        goal = str(arguments.get("goal", "")).strip()
        cwd = str(arguments.get("cwd", "")).strip() or str(
            self._default_cwd if self._default_cwd.is_dir() else working_dir
        )
        preview = goal[:100] + ("…" if len(goal) > 100 else "")
        return f"委派 CLI Agent ({provider}) · cwd={cwd}\n{preview}"
