"""DeepSeek provider passes thinking via openai extra_body."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aisuite.providers.deepseek_provider import DeepseekProvider


def test_deepseek_provider_moves_thinking_to_extra_body() -> None:
    with patch("aisuite.providers.deepseek_provider.openai.OpenAI") as openai_cls:
        client = MagicMock()
        openai_cls.return_value = client
        client.chat.completions.create.return_value = MagicMock(
            model_dump=lambda: {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}]
            }
        )
        provider = DeepseekProvider(api_key="sk-" + "a" * 32)
        provider.chat_completions_create(
            "deepseek-v4-flash",
            [{"role": "user", "content": "hi"}],
            temperature=0.0,
            thinking={"type": "disabled"},
            reasoning_effort="high",
        )
        kwargs = client.chat.completions.create.call_args.kwargs
        assert "thinking" not in kwargs
        assert "reasoning_effort" not in kwargs
        assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
        assert kwargs["extra_body"]["reasoning_effort"] == "high"
