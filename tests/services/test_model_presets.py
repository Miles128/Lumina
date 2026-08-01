"""Model catalog / provider presets for settings UI."""

from __future__ import annotations

from secretary.agent.harness_config import HarnessConfig
from secretary.services.agent_config import MODEL_PRESETS, PROVIDER_PRESETS


def test_provider_presets_default_to_flash() -> None:
    deepseek = PROVIDER_PRESETS["deepseek"]
    assert deepseek["model"] == "deepseek-v4-flash"
    assert deepseek["base_url"] == "https://api.deepseek.com/v1"


def test_model_presets_cover_common_providers() -> None:
    ids = {item["id"] for item in MODEL_PRESETS}
    assert "deepseek-v4-flash" in ids
    assert "deepseek-v4-pro" in ids
    assert "openai-gpt-4o" in ids
    assert "openai-gpt-4o-mini" in ids
    assert "openrouter-claude-sonnet" in ids
    for item in MODEL_PRESETS:
        assert item["base_url"]
        assert item["model"]
        assert item["provider"]
        assert item["label"]


def test_harness_defaults_include_thinking_knobs() -> None:
    cfg = HarnessConfig()
    assert cfg.thinking_mode == "auto"
    assert cfg.reasoning_effort == "high"
    assert cfg.strict_tools is False
