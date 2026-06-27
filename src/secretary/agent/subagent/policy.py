"""Spawn depth, quotas, and timeout limits for sub-agents."""

from __future__ import annotations

MAX_SPAWN_DEPTH = 1
MAX_SPAWNS_PER_TURN = 3
MAX_PARALLEL_EXPLORE = 3
EXPLORE_MAX_STEPS = 8
WORKER_MAX_STEPS = 12
VERIFY_MAX_STEPS = 6
PLAN_MAX_STEPS = 8

SUBAGENT_TIMEOUT_SEC = 120

BUILTIN_ARCHETYPES = frozenset({"explore", "worker", "verify", "plan"})
