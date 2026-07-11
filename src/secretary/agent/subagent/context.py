"""Per-turn spawn tracking for parent agent loops."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class SpawnContext:
    """Mutable counters for spawn policy enforcement on the parent turn.

    线程安全：record_spawn / child_context 通过内部锁保护，
    确保并行 explore 时 spawns_this_turn 计数正确。
    """

    parent_session_id: str
    depth: int = 0
    spawns_this_turn: int = 0
    trace_id: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def child_session_id(self, run_id: str) -> str:
        base = self.parent_session_id.strip() or "session"
        return f"{base}::sub::{run_id}"

    def record_spawn(self) -> None:
        with self._lock:
            self.spawns_this_turn += 1

    def get_spawns_this_turn(self) -> int:
        """Thread-safe read of spawns_this_turn."""
        with self._lock:
            return self.spawns_this_turn

    def child_context(self) -> SpawnContext:
        """Spawn context for a child run (depth + 1, same parent session)."""
        with self._lock:
            return SpawnContext(
                parent_session_id=self.parent_session_id,
                depth=self.depth + 1,
                spawns_this_turn=self.spawns_this_turn,
                trace_id=self.trace_id,
            )
