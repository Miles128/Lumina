"""Tests for kimi prompt insertion in CLI runner."""

from __future__ import annotations

from secretary.agent.cli_agent.runner import CliAgentRunner


def test_insert_prompt_after_flag() -> None:
    argv = ["kimi", "-p", "--output-format", "text", "-y"]
    result = CliAgentRunner._insert_prompt_after_flag(argv, "run tests", "-p")
    assert result == ["kimi", "-p", "run tests", "--output-format", "text", "-y"]
