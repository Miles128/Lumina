"""Tests for ShellTool reliability."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.loop import ShellTool


def test_shell_tool_runs_in_working_dir(tmp_path: Path) -> None:
    tool = ShellTool()
    output = tool.execute({"command": "pwd"}, tmp_path)
    assert str(tmp_path) in output


def test_shell_tool_truncates_large_output(tmp_path: Path) -> None:
    tool = ShellTool()
    output = tool.execute({"command": "python3 -c \"print('x' * 20000)\""}, tmp_path)
    assert "...[truncated]" in output
    assert len(output) <= ShellTool._MAX_OUTPUT_CHARS + 20


def test_shell_tool_reports_exit_code(tmp_path: Path) -> None:
    tool = ShellTool()
    output = tool.execute({"command": "exit 3"}, tmp_path)
    assert "[exit code: 3]" in output


def test_shell_tool_uses_home_when_cwd_missing(tmp_path: Path, monkeypatch) -> None:
    tool = ShellTool()
    missing = tmp_path / "missing-dir"
    output = tool.execute({"command": "pwd"}, missing)
    assert str(Path.home()) in output
