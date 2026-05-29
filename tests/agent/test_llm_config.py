"""Tests for LLM config resolution."""

from pathlib import Path

from secretary.agent.llm_config import is_placeholder_api_key, load_hermes_llm_config


def test_placeholder_key_detection() -> None:
    assert is_placeholder_api_key("sk-990...7755") is True
    assert is_placeholder_api_key("********") is True
    assert is_placeholder_api_key("sk-" + "a" * 32) is False


def test_load_hermes_prefers_env_over_masked_yaml(tmp_path: Path, monkeypatch) -> None:
    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()
    (hermes_dir / "config.yaml").write_text(
        "\n".join(
            [
                "model:",
                "  default: deepseek-v4-flash",
                "  provider: deepseek",
                "  base_url: https://api.deepseek.com",
                "  api_key: sk-990...7755",
            ]
        ),
        encoding="utf-8",
    )
    (hermes_dir / ".env").write_text(
        f"DEEPSEEK_API_KEY=sk-{'x' * 32}\nDEEPSEEK_BASE_URL=https://api.deepseek.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("secretary.agent.llm_config._HERMES_CONFIG", hermes_dir / "config.yaml")
    monkeypatch.setattr("secretary.agent.llm_config._HERMES_ENV", hermes_dir / ".env")

    config = load_hermes_llm_config()
    assert config is not None
    assert config.api_key.startswith("sk-")
    assert "..." not in config.api_key
    assert config.model == "deepseek-chat"
