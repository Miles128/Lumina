"""Tests for agent config store."""

from pathlib import Path

import pytest

from secretary.agent.llm_config import normalize_model_name
from secretary.config import Settings
from secretary.exceptions import AgentError
from secretary.services.agent_config import AgentConfigStore


def test_normalize_model_name_maps_hermes_alias() -> None:
    assert normalize_model_name("deepseek-v4-flash") == "deepseek-chat"


def test_agent_config_local_priority(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    store.update(
        {
            "provider": "deepseek",
            "api_key": "sk-local-test-key-0123456789",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "use_hermes_fallback": True,
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
