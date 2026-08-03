"""Tests for aisuite Client bridge."""

from __future__ import annotations

from secretary.agent.aisuite_bridge import (
    build_provider_configs,
    infer_provider_key,
    to_aisuite_model,
)
from secretary.agent.llm_config import LlmConfig


def _cfg(*, base_url: str, model: str) -> LlmConfig:
    return LlmConfig(
        api_key="sk-" + "a" * 32,
        base_url=base_url,
        model=model,
        source="env",
    )


def test_deepseek_provider_and_model_string() -> None:
    cfg = _cfg(base_url="https://api.deepseek.com/v1", model="deepseek-v4-flash")
    assert infer_provider_key(cfg) == "deepseek"
    assert to_aisuite_model(cfg) == "deepseek:deepseek-v4-flash"
    providers = build_provider_configs(cfg)
    assert providers["deepseek"]["api_key"].startswith("sk-")
    assert providers["deepseek"]["base_url"] == "https://api.deepseek.com"


def test_openai_compatible_custom_host() -> None:
    cfg = _cfg(base_url="https://example.com/v1", model="test-model")
    assert infer_provider_key(cfg) == "openai"
    assert to_aisuite_model(cfg) == "openai:test-model"
    assert build_provider_configs(cfg)["openai"]["base_url"] == "https://example.com/v1"


def test_openrouter_uses_openai_provider() -> None:
    cfg = _cfg(base_url="https://openrouter.ai/api/v1", model="openai/gpt-4o")
    assert infer_provider_key(cfg) == "openai"
    assert to_aisuite_model(cfg) == "openai:openai/gpt-4o"
