"""Tests for llm_client response parsing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from secretary.agent.llm_client import chat_completion, llm_usage_scope
from secretary.agent.llm_config import LlmConfig
from secretary.exceptions import AgentError


def _config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def _fake_post(payload: dict[str, object]) -> dict[str, object]:
    """Simulate httpx.Client.post(...).json() return value."""
    return payload


def test_chat_completion_accepts_string_content() -> None:
    payload = {"choices": [{"message": {"content": "hello"}}]}
    with patch(
        "secretary.agent.llm_client._non_stream_request",
        return_value=payload,
    ):
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
    with patch(
        "secretary.agent.llm_client._non_stream_request",
        return_value=payload,
    ):
        result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "line 1\nline 2"


def test_chat_completion_raises_on_empty_content() -> None:
    payload = {"choices": [{"message": {"content": []}}]}
    with patch(
        "secretary.agent.llm_client._non_stream_request",
        return_value=payload,
    ):
        with pytest.raises(AgentError, match="大模型"):
            chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)


def test_chat_completion_retries_once_on_empty_content() -> None:
    payload_empty = {"choices": [{"message": {"content": []}}]}
    payload_ok = {"choices": [{"message": {"content": "retry-ok"}}]}
    with patch(
        "secretary.agent.llm_client._non_stream_request",
        side_effect=[payload_empty, payload_ok],
    ):
        result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "retry-ok"


def test_chat_completion_with_tools_parses_tool_calls() -> None:
    from secretary.agent.llm_client import chat_completion_with_tools, schemas_to_openai_tools

    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "list_dir",
                                "arguments": "{\"path\": \".\"}",
                            },
                        }
                    ],
                }
            }
        ]
    }
    tools = schemas_to_openai_tools(
        [
            {
                "name": "list_dir",
                "description": "List directory",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            }
        ]
    )
    with patch(
        "secretary.agent.llm_client._tools_request",
        return_value=_fake_tools_result(payload),
    ):
        result = chat_completion_with_tools(
            _config(),
            [{"role": "user", "content": "list files"}],
            tools,
            temperature=0.0,
        )
    assert result.tool_calls[0].name == "list_dir"
    assert result.tool_calls[0].arguments["path"] == "."


def _fake_tools_result(payload: dict[str, object]):
    from secretary.agent.llm_client import _result_from_assistant_message

    msg = payload["choices"][0]["message"]
    assert isinstance(msg, dict)
    return _result_from_assistant_message(msg)


def test_chat_completion_with_tools_preserves_reasoning_content() -> None:
    from secretary.agent.llm_client import _result_from_assistant_message

    message = {
        "content": "",
        "reasoning_content": "Need to list files before answering.",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "arguments": "{\"path\": \".\"}",
                },
            }
        ],
    }
    parsed = _result_from_assistant_message(message)
    assert parsed.assistant_message["reasoning_content"] == "Need to list files before answering."
    assert parsed.assistant_message["tool_calls"][0]["id"] == "call_1"
    assert "reasoning_content" in parsed.assistant_message


def test_usage_tracking() -> None:
    payload = {
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
        "choices": [{"message": {"content": "ok"}}],
    }
    with patch(
        "secretary.agent.llm_client._non_stream_request",
        return_value=payload,
    ):
        with llm_usage_scope() as usage:
            result = chat_completion(_config(), [{"role": "user", "content": "hi"}], temperature=0.0)
    assert result == "ok"
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 19
