"""Native multi-tool calls in one model step must all execute when read-only."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.llm_client import ChatCompletionResult, LlmToolCall
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, FileReadTool, ListDirTool


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def test_native_batch_executes_all_read_only_tools(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha", encoding="utf-8")
    b.write_text("beta", encoding="utf-8")

    batch = ChatCompletionResult(
        content="",
        tool_calls=(
            LlmToolCall(id="call_a", name="file_read", arguments={"path": str(a)}),
            LlmToolCall(id="call_b", name="file_read", arguments={"path": str(b)}),
        ),
        assistant_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {
                        "name": "file_read",
                        "arguments": f'{{"path": "{a}"}}',
                    },
                },
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {
                        "name": "file_read",
                        "arguments": f'{{"path": "{b}"}}',
                    },
                },
            ],
        },
    )
    final = ChatCompletionResult(
        content="a 是 alpha，b 是 beta。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "a 是 alpha，b 是 beta。"},
    )

    loop = AgentLoop(
        _llm_config(),
        tools=[FileReadTool(), ListDirTool()],
        max_steps=4,
        working_dir=tmp_path,
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            side_effect=[batch, final],
        ),
    ):
        result = loop.run([{"role": "user", "content": "读 a.txt 和 b.txt"}], temperature=0.0)

    assert result.used_tools.count("file_read") == 2
    outputs = [step.tool_output or "" for step in result.steps if step.tool_call]
    assert any("alpha" in out for out in outputs)
    assert any("beta" in out for out in outputs)
    assert "alpha" in result.reply and "beta" in result.reply
