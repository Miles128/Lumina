"""DeepSeek thinking / reasoning_effort / cache usage options."""

from __future__ import annotations

from unittest.mock import patch

from secretary.agent.llm_client import (
    LlmUsage,
    chat_completion,
    chat_completion_with_tools,
    llm_usage_scope,
    schemas_to_openai_tools,
)
from secretary.agent.llm_config import (
    LlmConfig,
    model_supports_thinking,
    normalize_model_name,
)


def _deepseek_config(model: str = "deepseek-v4-flash") -> LlmConfig:
    return LlmConfig(
        api_key="sk-" + "a" * 32,
        base_url="https://api.deepseek.com/v1",
        model=model,
        source="env",
    )


def test_normalize_keeps_flash_and_maps_legacy_aliases() -> None:
    assert normalize_model_name("deepseek-v4-flash") == "deepseek-v4-flash"
    assert normalize_model_name("deepseek-v4-pro") == "deepseek-v4-pro"
    assert normalize_model_name("deepseek-chat") == "deepseek-v4-flash"
    assert normalize_model_name("deepseek-reasoner") == "deepseek-v4-flash"
    assert normalize_model_name("deepseek-v3.2") == "deepseek-v4-flash"
    assert normalize_model_name("") == "deepseek-v4-flash"


def test_model_supports_thinking() -> None:
    assert model_supports_thinking("deepseek-v4-flash") is True
    assert model_supports_thinking("deepseek-v4-pro") is True
    assert model_supports_thinking("gpt-4o") is False


def test_chat_completion_disables_thinking_by_default_for_deepseek() -> None:
    captured: dict[str, object] = {}

    def fake_request(client, url, payload, api_key):  # noqa: ANN001
        captured.update(payload)
        return {"choices": [{"message": {"content": "OK"}}], "usage": {}}

    with patch("secretary.agent.llm_client._non_stream_request", side_effect=fake_request):
        result = chat_completion(
            _deepseek_config(),
            [{"role": "user", "content": "hi"}],
            temperature=0.0,
        )
    assert result == "OK"
    assert captured.get("thinking") == {"type": "disabled"}
    assert "reasoning_effort" not in captured


def test_chat_completion_with_tools_enables_thinking_and_effort() -> None:
    captured: dict[str, object] = {}

    def fake_tools_request(client, url, payload, api_key):  # noqa: ANN001
        captured.update(payload)
        from secretary.agent.llm_client import _result_from_assistant_message

        return _result_from_assistant_message(
            {"role": "assistant", "content": "done", "tool_calls": []}
        )

    tools = schemas_to_openai_tools(
        [
            {
                "name": "list_dir",
                "description": "List",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    )
    with patch("secretary.agent.llm_client._tools_request", side_effect=fake_tools_request):
        chat_completion_with_tools(
            _deepseek_config(),
            [{"role": "user", "content": "list"}],
            tools,
            temperature=0.7,
            thinking="enabled",
            reasoning_effort="high",
        )
    assert captured.get("thinking") == {"type": "enabled"}
    assert captured.get("reasoning_effort") == "high"


def test_strict_tools_marks_functions_and_uses_beta_url() -> None:
    captured: dict[str, object] = {}
    captured_url: list[str] = []

    def fake_tools_request(client, url, payload, api_key):  # noqa: ANN001
        captured_url.append(url)
        captured.update(payload)
        from secretary.agent.llm_client import _result_from_assistant_message

        return _result_from_assistant_message(
            {"role": "assistant", "content": "done", "tool_calls": []}
        )

    tools = schemas_to_openai_tools(
        [
            {
                "name": "list_dir",
                "description": "List",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            }
        ]
    )
    with patch("secretary.agent.llm_client._tools_request", side_effect=fake_tools_request):
        chat_completion_with_tools(
            _deepseek_config(),
            [{"role": "user", "content": "list"}],
            tools,
            thinking="enabled",
            reasoning_effort="high",
            strict_tools=True,
        )
    assert "/beta/chat/completions" in captured_url[0]
    assert captured["tools"][0]["function"]["strict"] is True


def test_usage_tracks_prompt_cache_hit_miss() -> None:
    payload = {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        },
        "choices": [{"message": {"content": "ok"}}],
    }
    with patch(
        "secretary.agent.llm_client._non_stream_request",
        return_value=payload,
    ):
        with llm_usage_scope() as usage:
            chat_completion(
                _deepseek_config(),
                [{"role": "user", "content": "hi"}],
                thinking="disabled",
            )
    assert isinstance(usage, LlmUsage)
    assert usage.prompt_cache_hit_tokens == 80
    assert usage.prompt_cache_miss_tokens == 20
