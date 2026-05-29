"""Tests for llm_client response parsing."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from secretary.agent.llm_client import chat_completion, llm_usage_scope
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def test_chat_completion_accepts_string_content() -> None:
    payload = {"choices": [{"message": {"content": "hello"}}]}
    with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "hello"


def test_chat_completion_accepts_segmented_content_list() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "output_text", "text": "line 1"},
                        {"type": "output_text", "text": "line 2"},
                    ]
                }
            }
        ]
    }
    with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
        result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "line 1\nline 2"


def test_chat_completion_raises_on_empty_content() -> None:
    payload = {"choices": [{"message": {"content": []}}]}
    with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
        with pytest.raises(AgentError, match="大模型返回空内容"):
            chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)


def test_chat_completion_retries_once_on_empty_content() -> None:
    payload_empty = {"choices": [{"message": {"content": []}}]}
    payload_ok = {"choices": [{"message": {"content": "retry-ok"}}]}
    with patch(
        "urllib.request.urlopen",
        side_effect=[_FakeResponse(payload_empty), _FakeResponse(payload_ok)],
    ):
        result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "retry-ok"


def test_chat_completion_records_usage_in_scope() -> None:
    payload = {
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
        "choices": [{"message": {"content": "ok"}}],
    }
    with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
        with llm_usage_scope() as usage:
            result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "ok"
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 19
