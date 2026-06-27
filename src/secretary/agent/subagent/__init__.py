"""Sub-agent delegation (spawn tool + isolated child loops)."""

from secretary.agent.subagent.context import SpawnContext
from secretary.agent.subagent.policy import (
    EXPLORE_MAX_STEPS,
    MAX_SPAWN_DEPTH,
    MAX_SPAWNS_PER_TURN,
)
from secretary.agent.subagent.runner import SubAgentDeps, SubAgentRunner
from secretary.agent.subagent.spawn_tool import SpawnSubagentTool

__all__ = [
    "EXPLORE_MAX_STEPS",
    "MAX_SPAWNS_PER_TURN",
    "MAX_SPAWN_DEPTH",
    "SpawnContext",
    "SpawnSubagentTool",
    "SubAgentDeps",
    "SubAgentRunner",
]
