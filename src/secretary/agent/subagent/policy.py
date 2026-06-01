"""Spawn depth, quotas, and timeout limits for sub-agents."""

from __future__ import annotations

MAX_SPAWN_DEPTH = 1
MAX_SPAWNS_PER_TURN = 3
EXPLORE_MAX_STEPS = 8
SUBAGENT_TIMEOUT_SEC = 120

PHASE1_ARCHETYPES = frozenset({"explore"})
