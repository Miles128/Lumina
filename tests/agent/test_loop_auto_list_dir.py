"""Agent loop auto list_dir when model defers without tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.llm_client import ChatCompletionResult
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, ListDirTool


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def test_auto_list_dir_when_model_defers(tmp_path: Path) -> None:
    projects = tmp_path / "My Projects"
    projects.mkdir()
    (projects / "Lumina").mkdir()
    (projects / "Other").mkdir()

    defer_reply = ChatCompletionResult(
        content="好，我再查一下目录，稍等，查完告诉你有哪些项目。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "稍等"},
    )
    final_reply = ChatCompletionResult(
        content="目录下有 Lumina 和 Other 两个项目文件夹。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "done"},
    )

    loop = AgentLoop(
        _llm_config(),
        tools=[ListDirTool()],
        max_steps=4,
        working_dir=tmp_path,
    )

    user_msg = f"查一下 {projects} 里有哪些项目"

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            side_effect=[defer_reply, final_reply],
        ),
    ):
        result = loop.run([{"role": "user", "content": user_msg}], temperature=0.0)

    assert "list_dir" in result.used_tools
    assert any("Lumina" in (step.tool_output or "") for step in result.steps)
