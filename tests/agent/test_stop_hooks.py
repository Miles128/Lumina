"""Tests for loop stop hooks and progress events."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, ListDirTool, PendingConfirmation, ShellTool
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.stop_hooks import MaxIterationsStopHook
from secretary.agent.turn_runner import TurnRunner
from secretary.exceptions import AgentError
from secretary.services.file_auth import FileAuthService


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def test_third_person_reply_is_sanitized(tmp_path: Path) -> None:
    loop = AgentLoop(_llm_config(), tools=[ListDirTool()], working_dir=tmp_path)
    raw = "用户未明确需求，情绪化反问，需等待用户提出具体问题"
    with patch("secretary.agent.loop.chat_completion", return_value=raw):
        result = loop.run([{"role": "user", "content": "你又行了？"}], temperature=0.0)
    assert "抱歉，刚才那句不对" in result.reply
    assert "你又行了？" in result.reply


def test_loop_stops_early_when_model_answers_without_tool(tmp_path: Path) -> None:
    loop = AgentLoop(_llm_config(), tools=[ListDirTool()], max_steps=8, working_dir=tmp_path)
    events: list[ProgressEvent] = []
    loop._progress_callback = events.append  # noqa: SLF001
    with patch(
        "secretary.agent.loop.chat_completion",
        return_value="这是直接回答，不需要工具。",
    ) as mocked:
        result = loop.run([{"role": "user", "content": "你好"}], temperature=0.0)
    assert mocked.call_count == 1
    assert result.total_steps == 1
    assert any(event.kind == "iteration_completed" for event in events)


def test_max_iterations_hook_stops_loop_early(tmp_path: Path) -> None:
    hook = MaxIterationsStopHook(max_iterations=1)
    loop = AgentLoop(
        _llm_config(),
        tools=[ListDirTool()],
        max_steps=5,
        working_dir=tmp_path,
        stop_hooks=[hook],
    )
    raw = (
        "继续执行\n"
        "```tool-call\n"
        '{"name":"list_dir","arguments":{"path":"."}}\n'
        "```"
    )
    with patch("secretary.agent.loop.chat_completion", return_value=raw) as mocked:
        result = loop.run([{"role": "user", "content": "继续"}], temperature=0.0)
    assert mocked.call_count == 1
    assert "安全步数上限" in result.reply


def test_progress_callback_receives_iteration_and_final(tmp_path: Path) -> None:
    events: list[ProgressEvent] = []
    loop = AgentLoop(
        _llm_config(),
        tools=[ListDirTool()],
        working_dir=tmp_path,
        progress_callback=events.append,
    )
    with patch("secretary.agent.loop.chat_completion", return_value="直接答复"):
        result = loop.run([{"role": "user", "content": "hi"}], temperature=0.0)
    assert result.reply == "直接答复"
    assert [event.kind for event in events] == [
        "iteration_started",
        "reply_end",
        "iteration_completed",
        "final_reply",
    ]


def test_bash_block_with_waiting_text_is_inferred_as_shell_call(tmp_path: Path) -> None:
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], working_dir=tmp_path)
    raw = (
        "先搜：\n"
        "```bash\n"
        "pwd\n"
        "```\n"
        "等 shell 结果。"
    )
    with patch("secretary.agent.loop.chat_completion", return_value=raw):
        result = loop.run([{"role": "user", "content": "帮我查当前目录"}], temperature=0.0)
    assert result.pending_confirmation is None
    assert "shell" in result.used_tools


def test_inline_confirm_command_text_is_inferred_as_shell_call(tmp_path: Path) -> None:
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], working_dir=tmp_path)
    raw = "你需要确认才能执行：\n\n⚡ 执行命令: `pwd`\n\n是否允许？"
    with patch("secretary.agent.loop.chat_completion", return_value=raw):
        result = loop.run([{"role": "user", "content": "查当前目录"}], temperature=0.0)
    assert result.pending_confirmation is None
    assert "shell" in result.used_tools


def test_execute_confirmed_returns_tool_output_when_model_emits_followup_tool_call(
    tmp_path: Path,
) -> None:
    loop = AgentLoop(_llm_config(), tools=[ShellTool()], working_dir=tmp_path)
    pending = PendingConfirmation(
        action_id="act_1",
        tool_name="shell",
        arguments={"command": "printf done"},
        description="⚡ 执行命令: `printf done`",
        risk_level="high",
        confirmation_kind="shell",
    )
    raw = (
        "我先执行命令，再给你结果。\n"
        "```tool-call\n"
        '{"name":"shell","arguments":{"command":"pwd"}}\n'
        "```"
    )
    with patch("secretary.agent.loop.chat_completion", return_value=raw):
        result = loop.execute_confirmed(
            pending,
            [{"role": "user", "content": "请执行并告诉我结果"}],
            temperature=0.0,
        )
    assert "done" in result.reply


def test_orchestrator_confirmed_action_continues_loop_after_followup_tool_call(
    tmp_path: Path,
) -> None:
    orchestrator = TurnRunner(FileAuthService(tmp_path / "file_auth.json"))
    pending = PendingConfirmation(
        action_id="act_1",
        tool_name="shell",
        arguments={"command": "printf confirmed"},
        description="⚡ 执行命令: `printf confirmed`",
        risk_level="high",
        confirmation_kind="shell",
    )
    followup_tool = (
        "先读取目录，再给最终答案。\n"
        "```tool-call\n"
        '{"name":"list_dir","arguments":{"path":"."}}\n'
        "```"
    )
    final_answer = "最终答案：确认命令已执行，并且目录也读取完成。"

    with (
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            side_effect=AgentError("native tools unavailable"),
        ),
        patch("secretary.agent.loop.chat_completion", side_effect=[followup_tool, final_answer]) as mocked,
    ):
        result = orchestrator.run_confirmed_action(
            _llm_config(),
            tools=[ShellTool(), ListDirTool()],
            pending=pending,
            messages=[{"role": "user", "content": "执行命令后继续完成任务"}],
            temperature=0.0,
            working_dir=tmp_path,
        )

    assert result.reply == final_answer
    assert result.used_tools == ["shell", "list_dir"]
    assert mocked.call_count == 2

