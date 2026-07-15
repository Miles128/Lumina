"""Tests for F21 ReflectionTrigger — heuristic failure detection."""

from __future__ import annotations

from secretary.agent.reflection import ReflectionTrigger


def _make_loop_result(
    reply: str = "done",
    total_steps: int = 3,
    cancelled: bool = False,
    grounding_verified: bool = True,
    used_tools: list[str] | None = None,
):
    """Build a minimal LoopResult-like object for testing."""
    from secretary.agent.loop import LoopResult

    return LoopResult(
        reply=reply,
        steps=[],
        used_tools=used_tools or [],
        total_steps=total_steps,
        cancelled=cancelled,
        grounding_verified=grounding_verified,
    )


def test_no_failure_returns_none():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="done",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is None


def test_max_steps_exhausted():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(total_steps=20)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="incomplete",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "max_steps_exhausted"


def test_grounding_failed():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(grounding_verified=False)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="unverified reply",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "grounding_failed"


def test_turn_aborted():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(cancelled=True)
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="",
        loop_result=result,
        turn_status="cancelled",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "turn_aborted"


def test_user_correction_keyword():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    signal = trigger.evaluate(
        profile="build",
        user_message="不对，重新做",
        raw_reply="previous reply",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is not None
    assert signal.mode == "user_correction"


def test_user_correction_not_in_ask_profile():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    signal = trigger.evaluate(
        profile="ask",
        user_message="不对",
        raw_reply="reply",
        loop_result=result,
        turn_status="completed",
        tool_call_history=[],
    )
    assert signal is None


def test_verify_failed_detection():
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result()
    tool_history = [
        {"name": "spawn_subagent", "arguments": {"archetype": "verify"},
         "output": "Pass: False\nIssues found: test missing"},
    ]
    signal = trigger.evaluate(
        profile="build",
        user_message="implement feature",
        raw_reply="done",
        loop_result=result,
        turn_status="completed",
        tool_call_history=tool_history,
    )
    assert signal is not None
    assert signal.mode == "verify_failed"
    assert signal.verify_issues is not None


def test_priority_short_circuit_max_steps_over_verify():
    """F4 (max_steps) should take priority over F2 (verify_failed)."""
    trigger = ReflectionTrigger(max_steps=20)
    result = _make_loop_result(total_steps=20)
    tool_history = [
        {"name": "spawn_subagent", "arguments": {"archetype": "verify"},
         "output": "Pass: False"},
    ]
    signal = trigger.evaluate(
        profile="build",
        user_message="do something",
        raw_reply="",
        loop_result=result,
        turn_status="completed",
        tool_call_history=tool_history,
    )
    assert signal is not None
    assert signal.mode == "max_steps_exhausted"
