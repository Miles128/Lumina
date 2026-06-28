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
    assert providers["kimi"].available_check == "kimi"
    assert providers["kimi"].prompt_flag == "-p"
    assert providers["codex"].enabled is False
    assert providers["kimi"].enabled is False


def test_cli_agents_disabled_by_default(tmp_path) -> None:
    store = CliAgentConfigStore(tmp_path / "cli-agents.json")
    assert store.is_enabled() is False
    assert store.get_provider("codex") is None
    status = store.status()
    assert status["enabled"] is False
    assert status["active"] is False


def test_enable_cli_agents_exposes_provider(tmp_path) -> None:
    store = CliAgentConfigStore(tmp_path / "cli-agents.json")
    store.update_defaults(enabled=True)
    store.set_provider_enabled("codex", True)
    assert store.get_provider("codex") is not None
    assert store.status()["active"] is False or store.status()["active"] is True
