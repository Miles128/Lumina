"""FR-52: tunable harness parameters (defaults + clamp helpers)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TraceRetention = Literal["full", "summary", "off"]


class HarnessConfig(BaseModel):
    """Runtime knobs for the self-hosted agent harness.

    Hard limits such as ``MAX_SPAWN_DEPTH=1`` are never exposed here.
    """

    max_tool_rounds: int = Field(default=20, ge=1, le=64)
    light_max_steps: int = Field(default=3, ge=1, le=16)
    compaction_max_tokens: int = Field(default=24_000, ge=4_000, le=128_000)
    compaction_keep_tail: int = Field(default=8, ge=2, le=64)
    trace_retention: TraceRetention = "full"
    trace_retain_days: int = Field(default=30, ge=0, le=365)
    max_tool_output_chars: int = Field(default=12_000, ge=500, le=100_000)


def resolve_max_steps(harness: HarnessConfig, *, light_mode: bool) -> int:
    if light_mode:
        return harness.light_max_steps
    return harness.max_tool_rounds
