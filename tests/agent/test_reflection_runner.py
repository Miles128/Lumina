"""Tests for F21 ReflectionRunner — spawns reflect sub-agent and parses output."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from secretary.agent.reflection import ReflectionRunner
from secretary.agent.reflection.trigger import FailureSignal


def _make_signal(mode: str = "verify_failed") -> FailureSignal:
    return FailureSignal(
        mode=mode,
        summary="test failure",
        user_message="do something",
        raw_reply="reply text",
        tool_calls_summary=["file_read: ok"],
        verify_issues="issues found",
    )


def _build_runner() -> ReflectionRunner:
    """Build ReflectionRunner with mocked SubAgentRunner."""
    runner = ReflectionRunner.__new__(ReflectionRunner)
    runner._runner = MagicMock()
    return runner


def test_reflection_runner_parses_valid_json():
    """ReflectionRunner must extract JSON from reflector output."""
    runner = _build_runner()
    reflector_output = (
        'Some preamble text\n'
        '{"failure_summary": "bad patch", "root_cause": "no signature check", '
        '"lesson": "verify first", "related_files": ["src/foo.py"], '
        '"failure_tags": ["patch_error"]}\n'
        'trailing text'
    )
    runner._runner.run_from_tool.return_value = reflector_output
    signal = _make_signal()
    result = runner.run(signal, working_dir=Path("/tmp"), parent_session_id="sess1")
    parsed = json.loads(result)
    assert parsed["failure_summary"] == "bad patch"
    assert parsed["lesson"] == "verify first"


def test_reflection_runner_returns_empty_on_error_output():
    """If reflector returns Error: string, return empty string."""
    runner = _build_runner()
    runner._runner.run_from_tool.return_value = "Error: sub-agent failed: timeout"
    signal = _make_signal()
    result = runner.run(signal, working_dir=Path("/tmp"), parent_session_id="sess1")
    assert result == ""


def test_reflection_runner_returns_empty_on_exception():
    """If reflector raises, return empty string (not crash)."""
    runner = _build_runner()
    runner._runner.run_from_tool.side_effect = RuntimeError("boom")
    signal = _make_signal()
    result = runner.run(signal, working_dir=Path("/tmp"), parent_session_id="sess1")
    assert result == ""
