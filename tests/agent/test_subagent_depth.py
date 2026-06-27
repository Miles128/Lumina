"""Spawn depth policy: exactly one sub-agent layer."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.custom import load_custom_archetypes
from secretary.agent.subagent.policy import MAX_SPAWN_DEPTH
from secretary.agent.subagent.runner import SubAgentRunner
from secretary.agent.subagent import SubAgentDeps
from secretary.agent.llm_config import LlmConfig
from secretary.memory.db import MemoryStore
from secretary.memory.hermes_memory import HermesMemory


def _deps(tmp_path: Path) -> SubAgentDeps:
    return SubAgentDeps(
        llm_config=LlmConfig(
            api_key="k",
            base_url="https://example.com/v1",
            model="m",
            source="env",
        ),
        file_auth=None,
        memory_store=MemoryStore(tmp_path / "memory.db"),
        hermes=HermesMemory(tmp_path),
    )


def test_child_context_increments_depth() -> None:
    parent = SpawnContext(parent_session_id="s1", depth=0)
    child = parent.child_context()
    assert child.depth == 1
    assert child.parent_session_id == "s1"


def test_spawn_blocked_at_max_depth(tmp_path: Path) -> None:
    runner = SubAgentRunner(_deps(tmp_path))
    at_limit = SpawnContext(parent_session_id="s1", depth=MAX_SPAWN_DEPTH)
    output = runner.run_from_tool(
        {"goal": "probe", "archetype": "explore"},
        at_limit,
        tmp_path,
    )
    assert "depth limit" in output


def test_custom_md_primary_mode_not_listed_as_subagent(tmp_path: Path) -> None:
    sub_dir = tmp_path / "subagents"
    sub_dir.mkdir()
    (sub_dir / "orchestrator-lite.md").write_text(
        "---\nname: orchestrator-lite\nmode: primary\ntools: list_dir\n---\n"
        "Primary-only agent definition.\n",
        encoding="utf-8",
    )
    (sub_dir / "scout.md").write_text(
        "---\nname: scout\nmode: subagent\ntools: list_dir,file_read\n---\n"
        "Scout sub-agent.\n",
        encoding="utf-8",
    )
    specs = load_custom_archetypes(sub_dir)
    assert "orchestrator-lite" not in specs
    assert "scout" in specs
