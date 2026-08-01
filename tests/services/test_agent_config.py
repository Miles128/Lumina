"""Tests for agent config store."""

from pathlib import Path

import pytest

from secretary.agent.llm_config import normalize_model_name
from secretary.config import Settings
from secretary.exceptions import AgentError
from secretary.services.agent_config import AgentConfigStore


def test_normalize_model_name_maps_hermes_alias() -> None:
    assert normalize_model_name("deepseek-v4-flash") == "deepseek-v4-flash"
    assert normalize_model_name("deepseek-chat") == "deepseek-v4-flash"


def test_agent_config_local_priority(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    store.update(
        {
            "provider": "deepseek",
            "api_key": "sk-local-test-key-0123456789",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        }
    )
    settings = Settings(data_dir=tmp_path / "data")
    resolved = store.get_view(settings)
    assert resolved.status == "ready"
    assert resolved.active_source == "local"


def test_import_from_hermes_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    monkeypatch.setattr(
        "secretary.services.agent_config.load_hermes_llm_config",
        lambda: None,
    )
    with pytest.raises(AgentError, match="Hermes"):
        store.import_from_hermes()


def test_agent_config_response_style_defaults_to_standard(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    settings = Settings(data_dir=tmp_path / "data")
    view = store.get_view(settings)
    assert view.response_style == "standard"


def test_shell_working_dir_persisted(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    store.update({"shell_working_dir": str(tmp_path)})
    view = store.get_view(Settings(data_dir=tmp_path / "data"))
    assert view.shell_working_dir == str(tmp_path)


def test_background_config_persisted_and_resolved(tmp_path: Path) -> None:
    from secretary.services.agent_config import resolve_background_config

    store = AgentConfigStore(tmp_path / "agent.json")
    settings = Settings(
        data_dir=tmp_path / "data",
        think_enabled=False,
        memory_summary_enabled=False,
    )
    # No background key yet → Settings / env fallback
    bg = resolve_background_config(settings, store)
    assert bg.think_enabled is False
    assert bg.memory_summary_enabled is False

    store.update(
        {
            "background": {
                "think_enabled": True,
                "think_interval_hours": 8,
                "memory_summary_enabled": True,
                "memory_summary_hour": 21,
            }
        }
    )
    bg2 = resolve_background_config(settings, store)
    assert bg2.think_enabled is True
    assert bg2.think_interval_hours == 8
    assert bg2.memory_summary_enabled is True
    assert bg2.memory_summary_hour == 21
