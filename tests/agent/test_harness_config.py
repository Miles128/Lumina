"""FR-52: harness tunable parameters on agent config."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.harness_config import HarnessConfig, resolve_max_steps
from secretary.config import Settings
from secretary.services.agent_config import AgentConfigStore


def test_harness_defaults() -> None:
    cfg = HarnessConfig()
    assert cfg.max_tool_rounds == 20
    assert cfg.light_max_steps == 3
    assert cfg.compaction_max_tokens == 24_000
    assert cfg.compaction_keep_tail == 8
    assert cfg.trace_retention == "full"
    assert cfg.trace_retain_days == 30


def test_harness_persisted_on_agent_config(tmp_path: Path) -> None:
    store = AgentConfigStore(tmp_path / "agent.json")
    store.update(
        {
            "harness": {
                "max_tool_rounds": 12,
                "light_max_steps": 2,
                "compaction_max_tokens": 16_000,
                "compaction_keep_tail": 6,
                "trace_retention": "summary",
                "trace_retain_days": 7,
            }
        }
    )
    doc = store.load()
    assert doc.harness.max_tool_rounds == 12
    assert doc.harness.light_max_steps == 2
    assert doc.harness.compaction_max_tokens == 16_000
    assert doc.harness.trace_retention == "summary"
    view = store.get_view(Settings(data_dir=tmp_path / "data"))
    assert view.harness.max_tool_rounds == 12


def test_resolve_max_steps_uses_harness() -> None:
    cfg = HarnessConfig(max_tool_rounds=15, light_max_steps=2)
    assert resolve_max_steps(cfg, light_mode=True) == 2
    assert resolve_max_steps(cfg, light_mode=False) == 15
