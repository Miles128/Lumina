"""Deepseek provider for the aisuite (Lumina fork)."""

import os

import openai

from aisuite.provider import LLMError, Provider
from aisuite.providers.message_converter import OpenAICompliantMessageConverter

# OpenAI Python SDK rejects these as create() kwargs; DeepSeek accepts them in JSON body.
_DEEPSEEK_EXTRA_BODY_KEYS = ("thinking", "reasoning_effort")


# pylint: disable=too-few-public-methods
class DeepseekProvider(Provider):
    """Provider for Deepseek (Lumina: custom base_url + thinking via extra_body)."""

    def __init__(self, **config):
        """
        Initialize the DeepSeek provider with the given configuration.
        Pass the entire configuration dictionary to the OpenAI client constructor.
        """
        config.setdefault("api_key", os.getenv("DEEPSEEK_API_KEY"))
        if not config["api_key"]:
            raise ValueError(
                "DeepSeek API key is missing. Please provide it in the config or "
                "set the DEEPSEEK_API_KEY environment variable."
            )
        # Lumina patch: honor caller base_url (v1 / beta / custom gateway).
        config.setdefault("base_url", "https://api.deepseek.com")

        self.client = openai.OpenAI(**config)
        self.transformer = OpenAICompliantMessageConverter()

    def chat_completions_create(self, model, messages, **kwargs):
        # Lumina patch: move DeepSeek-only fields into extra_body for openai SDK.
        extra_body = dict(kwargs.pop("extra_body", None) or {})
        for key in _DEEPSEEK_EXTRA_BODY_KEYS:
            if key in kwargs:
                extra_body[key] = kwargs.pop(key)
        if extra_body:
            kwargs["extra_body"] = extra_body
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs,
            )
            return self.transformer.convert_response(response.model_dump())
        except Exception as e:
            raise LLMError(f"An error occurred: {e}") from e
