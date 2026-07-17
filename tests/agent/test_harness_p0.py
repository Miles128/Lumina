"""Tests for harness P0: session store, turn runner, delegation, progress schema."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from secretary.agent.delegation import delegation_from_cli, format_subagent_result
from secretary.agent.loop import LoopResult
from secretary.agent.progress_events import ProgressEvent, progress_event_payload
from secretary.agent.session_store import SessionStore
from secretary.agent.turn_models import PROGRESS_SCHEMA_VERSION
from secretary.agent.turn_runner import AgentTurnPlan, TurnRunner, bind_turn_progress
from secretary.services.file_auth import FileAuthService


def test_session_store_start_and_clear() -> None:
    store = SessionStore()
    turn = store.start_turn(trace_id="t1", thread_id="th1", user_message="hello")
    assert store.get_turn("t1") is turn
    assert turn.turn_id.startswith("turn_")
    store.clear_turn("t1")
    assert store.get_turn("t1") is None


def test_progress_payload_schema_v2() -> None:
    payload = progress_event_payload(
        ProgressEvent(kind="tool_started", iteration=1, tool_name="shell", turn_id="turn_x")
    )
    assert payload["schema_version"] == PROGRESS_SCHEMA_VERSION
    assert payload["turn_id"] == "turn_x"


def test_bind_turn_progress_adds_item_ids() -> None:
    store = SessionStore()
    turn = store.start_turn(trace_id="t2", thread_id="th2", user_message="hi")
    seen: list[str] = []

    def capture(event: ProgressEvent) -> None:
        seen.append(event.item_id)

    wrapped = bind_turn_progress(capture, turn)
    assert wrapped is not None
    wrapped(ProgressEvent(kind="iteration_started", iteration=1))
    wrapped(ProgressEvent(kind="tool_started", iteration=1, tool_name="shell"))
    assert len(seen) == 2
    assert seen[0] != seen[1]


def test_delegation_tool_output_unified() -> None:
    sub = format_subagent_result(
        LoopResult(reply="done", steps=[], used_tools=["file_read"], files_read=["a.py"], total_steps=1),
        run_id="r1",
        archetype="explore",
        goal="find auth",
    )
    cli = delegation_from_cli(
        run_id="r2",
        provider="codex",
        goal="fix bug",
        summary="patched",
        success=True,
        exit_code=0,
    ).to_tool_output()
    assert sub.startswith("[subagent:explore:r1]")
    assert cli.startswith("[cli:codex:r2]")


def test_turn_runner_emits_turn_lifecycle(tmp_path) -> None:
    file_auth = FileAuthService(tmp_path / "file_auth.json")
    runner = TurnRunner(file_auth)
    turn = runner.session_store.start_turn(trace_id="trace", thread_id="t", user_message="go")
    events: list[ProgressEvent] = []

    fake_result = LoopResult(reply="ok", steps=[], used_tools=[], total_steps=1)

    fake_loop = MagicMock()
    fake_loop.run.return_value = fake_result
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "secretary.agent.turn_runner.AgentLoop",
            MagicMock(return_value=fake_loop),
        )
        plan = AgentTurnPlan(messages=[{"role": "user", "content": "go"}], max_steps=3, tools=[])
        runner.run_agent_turn(
            MagicMock(),
            plan,
            temperature=0.1,
            progress_callback=events.append,
            turn=turn,
        )

    kinds = [event.kind for event in events]
    assert kinds[0] == "turn_started"
    assert kinds[-1] == "turn_completed"
