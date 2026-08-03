"""Bridge Lumina LlmConfig ↔ vendored aisuite Client."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from aisuite import Client

from secretary.agent.llm_config import LlmConfig


def infer_provider_key(config: LlmConfig) -> str:
    """Map Lumina base_url / model to an aisuite provider key."""
    host = (urlparse(config.base_url).hostname or "").lower()
    model = config.model.strip().lower()
    if "deepseek" in host or model.startswith("deepseek"):
        return "deepseek"
    if "openrouter" in host:
        return "openai"
    if "anthropic" in host or model.startswith("claude"):
        return "anthropic"
    return "openai"


def to_aisuite_model(config: LlmConfig) -> str:
    """Return ``provider:model`` for aisuite Completions.create."""
    provider = infer_provider_key(config)
    model = config.model.strip()
    if ":" in model:
        return model
    return f"{provider}:{model}"


def build_provider_configs(config: LlmConfig) -> dict[str, dict[str, Any]]:
    """Provider config dict suitable for ``aisuite.Client``."""
    provider = infer_provider_key(config)
    entry: dict[str, Any] = {"api_key": config.api_key}
    base = config.base_url.strip().rstrip("/")
    if provider == "deepseek":
        # DeepSeek OpenAI client expects host without forcing /v1 twice.
        if base.endswith("/v1"):
            entry["base_url"] = base[:-3] or base
        elif base.endswith("/beta"):
            entry["base_url"] = base
        else:
            entry["base_url"] = base
    else:
        entry["base_url"] = base if base.endswith("/v1") or base.endswith("/beta") else base
    return {provider: entry}


def build_aisuite_client(config: LlmConfig) -> Client:
    return Client(provider_configs=build_provider_configs(config))


def response_to_openai_dict(response: Any) -> dict[str, Any]:
    """Normalize aisuite / OpenAI SDK responses to a plain OpenAI-shaped dict."""
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
        if isinstance(dumped, dict):
            return dumped
    # ChatCompletionResponse / SDK object with .choices
    choices_out: list[dict[str, Any]] = []
    choices = getattr(response, "choices", None) or []
    for choice in choices:
        message = getattr(choice, "message", None)
        msg_dict: dict[str, Any]
        if isinstance(message, dict):
            msg_dict = dict(message)
        elif message is None:
            msg_dict = {"role": "assistant", "content": ""}
        elif hasattr(message, "model_dump"):
            msg_dict = message.model_dump()
        else:
            msg_dict = {
                "role": getattr(message, "role", "assistant"),
                "content": getattr(message, "content", "") or "",
            }
            reasoning = getattr(message, "reasoning_content", None)
            if isinstance(reasoning, str):
                msg_dict["reasoning_content"] = reasoning
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                serialized: list[dict[str, Any]] = []
                for call in tool_calls:
                    if isinstance(call, dict):
                        serialized.append(call)
                        continue
                    fn = getattr(call, "function", None)
                    if fn is None:
                        continue
                    if isinstance(fn, dict):
                        fn_dict = fn
                    else:
                        fn_dict = {
                            "name": getattr(fn, "name", ""),
                            "arguments": getattr(fn, "arguments", "{}"),
                        }
                    serialized.append(
                        {
                            "id": getattr(call, "id", ""),
                            "type": "function",
                            "function": fn_dict,
                        }
                    )
                msg_dict["tool_calls"] = serialized
        choices_out.append({"message": msg_dict})
    usage = getattr(response, "usage", None)
    body: dict[str, Any] = {"choices": choices_out}
    if usage is not None:
        if hasattr(usage, "model_dump"):
            body["usage"] = usage.model_dump()
        elif isinstance(usage, dict):
            body["usage"] = usage
    return body
