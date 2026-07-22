"""Working directory must be visible in AgentLoop tool instructions."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, ListDirTool


def test_loop_instruction_includes_working_dir(tmp_path: Path) -> None:
    loop = AgentLoop(
        LlmConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
            source="env",
        ),
        tools=[ListDirTool()],
        working_dir=tmp_path,
    )
    instruction = loop._build_instruction(
        [ListDirTool().schema()],
        native=True,
    )
    assert f"Working directory (cwd): {tmp_path.resolve()}" in instruction
