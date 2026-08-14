"""Sub-agent archetype registry (consumed by the SDK as_tool backend)."""

from secretary.agent.subagent.registry import (
    ArchetypeSpec,
    get_archetype,
    list_archetype_names,
)

__all__ = [
    "ArchetypeSpec",
    "get_archetype",
    "list_archetype_names",
]
