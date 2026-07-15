"""Tests for sub-agent archetype registration (F21 reflect archetype)."""

from __future__ import annotations


def test_reflect_archetype_registered():
    """F21: reflect archetype must be in BUILTIN_ARCHETYPES."""
    from secretary.agent.subagent.policy import BUILTIN_ARCHETYPES, REFLECT_MAX_STEPS
    assert "reflect" in BUILTIN_ARCHETYPES
    assert REFLECT_MAX_STEPS == 4


def test_get_reflect_archetype_spec():
    """F21: get_archetype('reflect') must return ArchetypeSpec with correct config."""
    from secretary.agent.subagent.registry import get_archetype
    spec = get_archetype("reflect")
    assert spec is not None
    assert spec.name == "reflect"
    assert spec.max_steps == 4
    assert "reflection" in spec.system_prompt.lower() or "reflect" in spec.system_prompt.lower()
    # Tools must be read-only
    assert "file_write" not in (spec.tool_names or frozenset())
    assert "shell" not in (spec.tool_names or frozenset())
    assert "patch" not in (spec.tool_names or frozenset())


def test_reflect_archetype_in_list():
    """F21: list_archetype_names must include reflect."""
    from secretary.agent.subagent.registry import list_archetype_names
    names = list_archetype_names()
    assert "reflect" in names
