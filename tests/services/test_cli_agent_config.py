"""Tests for CLI agent config store."""

from __future__ import annotations

from secretary.services.cli_agent_config import (
    CliAgentConfigDocument,
    CliAgentConfigStore,
    CliProviderConfig,
    default_providers,
)


def test_cli_agent_config_merges_defaults(tmp_path) -> None:
    path = tmp_path / "cli-agents.json"
    store = CliAgentConfigStore(path)
    loaded = store.load()
    assert "codex" in loaded.providers
    assert loaded.providers["codex"].command == "codex"


def test_cli_agent_upsert_and_remove(tmp_path) -> None:
    store = CliAgentConfigStore(tmp_path / "cli-agents.json")
    store.upsert_provider(
        "custom",
        CliProviderConfig(command="echo", args=["hi"], enabled=True, available_check="echo"),
    )
    persisted = store.load_persisted()
    assert "custom" in persisted.providers
    assert store.remove_provider("custom") is True
    assert "custom" not in store.load_persisted().providers


def test_get_provider_respects_enabled(tmp_path) -> None:
    store = CliAgentConfigStore(tmp_path / "cli-agents.json")
    store.save(
        CliAgentConfigDocument(
            providers={
                "demo": CliProviderConfig(
                    command="echo",
                    args=[],
                    enabled=False,
                    available_check="echo",
                )
            }
        )
    )
    assert store.get_provider("demo") is None


def test_default_providers_have_checks() -> None:
    providers = default_providers()
    assert providers["codex"].available_check == "codex"
    assert providers["claude"].prompt_mode == "argv_tail"
    assert providers["opencode"].prompt_mode == "stdin"
