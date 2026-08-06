"""Thought text in progress details must not be truncated for harness UI."""

from __future__ import annotations

from secretary.agent.loop import _combine_thought_and_args_detail, _progress_detail_preview


def test_progress_detail_preview_still_truncates_generic_text() -> None:
    long = "a" * 500
    preview = _progress_detail_preview(long)
    assert len(preview) < len(long)
    assert preview.endswith("…")


def test_combine_keeps_full_thought_truncates_args() -> None:
    thought = "思考" * 200  # well over 320 chars
    args = "args:" + ("b" * 400)
    combined = _combine_thought_and_args_detail(thought, args)
    assert thought in combined
    assert "args:" in combined
    # args portion should be truncated via preview
    assert len(combined) < len(thought) + len(args)


def test_combine_thought_only_keeps_separator_for_ui_peel() -> None:
    thought = "only thought " + ("c" * 100)
    combined = _combine_thought_and_args_detail(thought, "")
    assert combined.startswith(thought)
    assert "\n\n" in combined
