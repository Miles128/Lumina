"""Turn / session models for harness-layer event correlation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

TurnStatus = Literal["running", "paused", "completed", "failed"]

PROGRESS_SCHEMA_VERSION = 2


@dataclass
class TurnContext:
    """One user message → agent loop lifecycle (maps to Codex Turn)."""

    turn_id: str
    trace_id: str
    thread_id: str = ""
    user_message: str = ""
    parent_turn_id: str = ""
    child_id: str = ""
    status: TurnStatus = "running"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    _item_seq: int = field(default=0, repr=False)

    @classmethod
    def create(
        cls,
        *,
        trace_id: str,
        thread_id: str = "",
        user_message: str = "",
        parent_turn_id: str = "",
        child_id: str = "",
    ) -> TurnContext:
        return cls(
            turn_id=f"turn_{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            thread_id=thread_id,
            user_message=user_message[:4000],
            parent_turn_id=parent_turn_id,
            child_id=child_id,
        )

    def next_item_id(self) -> str:
        self._item_seq += 1
        return f"{self.turn_id}:{self._item_seq}"
