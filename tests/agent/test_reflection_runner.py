"""Tests for F21 ReflectionRunner — runs reflect prompt and parses output."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from secretary.agent.llm_config import LlmConfig
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
    llm = LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )
    return ReflectionRunner(
        llm_config=llm,
        file_auth=MagicMock(),
        memory_store=MagicMock(),
        memory=MagicMock(),
        lumina_dir=None,
    )


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
    with patch(
        "secretary.agent.reflection.runner.chat_completion",
        return_value=reflector_output,
    ):
        result = runner.run(_make_signal(), working_dir=Path("/tmp"), parent_session_id="sess1")
    parsed = json.loads(result)
    assert parsed["failure_summary"] == "bad patch"
    assert parsed["lesson"] == "verify first"


def test_reflection_runner_returns_empty_on_error_output():
    """If reflector returns Error: string, return empty string."""
    runner = _build_runner()
    with patch(
        "secretary.agent.reflection.runner.chat_completion",
        return_value="Error: sub-agent failed: timeout",
    ):
        result = runner.run(_make_signal(), working_dir=Path("/tmp"), parent_session_id="sess1")
    assert result == ""


def test_reflection_runner_returns_empty_on_exception():
    """If reflector raises, return empty string (not crash)."""
    runner = _build_runner()
    with patch(
        "secretary.agent.reflection.runner.chat_completion",
        side_effect=RuntimeError("boom"),
    ):
        result = runner.run(_make_signal(), working_dir=Path("/tmp"), parent_session_id="sess1")
    assert result == ""
