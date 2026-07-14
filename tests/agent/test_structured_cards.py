"""Tests for structured card tools."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.structured_cards import (
    EmitCardTool,
    is_loop_short_circuit_output,
    is_structured_card_output,
)


def test_emit_summary_card() -> None:
    out = EmitCardTool().execute(
        {"kind": "summary", "title": "Done", "bullets": ["one"]},
        Path("."),
    )
    assert is_structured_card_output(out)
    assert is_loop_short_circuit_output(out)
    assert "SUMMARY_CARD" in out
