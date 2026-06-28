"""Per-turn spawn tracking for parent agent loops."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpawnContext:
    """Mutable counters for spawn policy enforcement on the parent turn."""

    parent_session_id: str
    depth: int = 0
    spawns_this_turn: int = 0
    trace_id: str = ""

    def child_session_id(self, run_id: str) -> str:
        base = self.parent_session_id.strip() or "session"
        return f"{base}::sub::{run_id}"

    def record_spawn(self) -> None:
        self.spawns_this_turn += 1

    def child_context(self) -> SpawnContext:
        """Spawn context for a child run (depth + 1, same parent session)."""
        return SpawnContext(
            parent_session_id=self.parent_session_id,
            depth=self.depth + 1,
            spawns_this_turn=self.spawns_this_turn,
            trace_id=self.trace_id,
        )
