"""Explicit workspace triggers an unconditional step-0 list_dir preflight.

When the user selected a folder for the turn (``explicit_working_dir=True``),
the loop must pre-read the workspace top level even if the user's message is
not a filesystem question — so the model starts with real entry names instead
of hallucinating paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.grounding import is_filesystem_question
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


def test_explicit_workspace_preflights_non_fs_question(tmp_path: Path) -> None:
    workspace = tmp_path / "StockResearch"
    workspace.mkdir()
    (workspace / "README.md").write_text("# StockResearch", encoding="utf-8")
    (workspace / "src").mkdir()
    (workspace / "pyproject.toml").write_text("", encoding="utf-8")

    # "分析 StockResearch" carries no filesystem marker / path → not a fs question.
    user_msg = "分析 StockResearch"
    assert is_filesystem_question(user_msg) is False

    final_reply = ChatCompletionResult(
        content="已读取工作区，顶层有 README.md、src、pyproject.toml。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "done"},
    )

    loop = AgentLoop(
        _llm_config(),
        tools=[ListDirTool()],
        max_steps=3,
        working_dir=workspace,
        explicit_working_dir=True,
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            return_value=final_reply,
        ),
    ):
        result = loop.run([{"role": "user", "content": user_msg}], temperature=0.0)

    # Preflight ran list_dir on the workspace itself.
    assert "list_dir" in result.used_tools
    preflight = result.steps[0]
    assert preflight.tool_call is not None
    assert preflight.tool_call.name == "list_dir"
    assert str(workspace) in (preflight.tool_output or "")
    # Real top-level entries are captured as read evidence.
    assert "README.md" in (preflight.tool_output or "")
    assert "pyproject.toml" in (preflight.tool_output or "")


def test_no_explicit_workspace_skips_preflight_for_non_fs_question(tmp_path: Path) -> None:
    workspace = tmp_path / "StockResearch"
    workspace.mkdir()
    (workspace / "README.md").write_text("# StockResearch", encoding="utf-8")

    final_reply = ChatCompletionResult(
        content="通用回答，未读盘。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "done"},
    )

    loop = AgentLoop(
        _llm_config(),
        tools=[ListDirTool()],
        max_steps=3,
        working_dir=workspace,
        explicit_working_dir=False,
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            return_value=final_reply,
        ),
    ):
        result = loop.run([{"role": "user", "content": "分析 StockResearch"}], temperature=0.0)

    assert "list_dir" not in result.used_tools


def test_filesystem_question_preflights_working_dir_when_no_path(tmp_path: Path) -> None:
    """FS questions with no extractable path still list_dir the loop cwd."""
    workspace = tmp_path / "proj"
    workspace.mkdir()
    (workspace / "README.md").write_text("# proj", encoding="utf-8")

    user_msg = "这个目录有什么文件"
    assert is_filesystem_question(user_msg) is True

    final_reply = ChatCompletionResult(
        content="顶层有 README.md。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "done"},
    )

    loop = AgentLoop(
        _llm_config(),
        tools=[ListDirTool()],
        max_steps=3,
        working_dir=workspace,
        explicit_working_dir=False,
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            return_value=final_reply,
        ),
    ):
        result = loop.run([{"role": "user", "content": user_msg}], temperature=0.0)

    assert "list_dir" in result.used_tools
    assert "README.md" in (result.steps[0].tool_output or "")
