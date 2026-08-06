"""Tests for the OpenAI Agents SDK backend (HITL pause/resume mapping)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from secretary.agent.agents_sdk_runtime import (
    _pending_from_interruption,
    _split_system_and_input,
    run_with_agents_sdk,
    wrap_lumina_tools,
)
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import PendingConfirmation
from secretary.agent.tools.fs import FileWriteTool, ListDirTool


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        source="env",
    )


def _fake_interruption(tool_name: str = "write", arguments: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        name=tool_name,
        arguments=arguments or {"path": "/tmp/x.txt", "content": "x"},
        agent=SimpleNamespace(name="lumina"),
    )


def _fake_result(
    *,
    final_output: str = "done",
    interruptions: list[Any] | None = None,
) -> Any:
    return SimpleNamespace(
        final_output=final_output,
        interruptions=interruptions or [],
        steps=[],
        to_state=lambda: SimpleNamespace(
            to_string=lambda: "sdk-state-json",
            get_interruptions=lambda: interruptions or [],
            approve=lambda item, always_approve=False: None,
        ),
    )


def test_split_system_and_input() -> None:
    instructions, rest = _split_system_and_input(
        [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ]
    )
    assert instructions == "SYS"
    assert rest == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]


def test_wrap_lumina_tools_builds_function_tools() -> None:
    tools = [FileWriteTool(), ListDirTool()]
    wrapped = wrap_lumina_tools(
        tools,
        Path("/tmp"),
        needs_confirm=lambda name, args: name == "write",
    )
    by_name = {tool.name: tool for tool in wrapped}
    assert set(by_name) == {"write", "ls"}
    assert by_name["write"].description
    assert "path" in by_name["write"].params_json_schema["properties"]
    # needs_approval is an async callable wired to the confirm policy.
    assert by_name["write"].needs_approval is not None
    assert asyncio.run(by_name["write"].needs_approval(None, {"path": "/x"}, "id")) is True
    assert by_name["ls"].needs_approval is not None
    assert asyncio.run(by_name["ls"].needs_approval(None, {"path": "/x"}, "id")) is False


def test_pending_from_interruption_maps_kind_and_diff(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    monkeypatch.setattr(
        agents_sdk_runtime,
        "tool_requires_confirmation",
        lambda tool, arguments, **kwargs: (True, "write_new"),
    )
    pending, step = _pending_from_interruption(
        _fake_interruption(),
        tools_by_name={"write": FileWriteTool()},
        working_dir=Path("/tmp"),
        require_confirm=None,
        sdk_state="STATE",
    )
    assert isinstance(pending, PendingConfirmation)
    assert pending.tool_name == "write"
    assert pending.sdk_state == "STATE"
    assert pending.confirmation_kind == "write_new"
    assert step.needs_confirmation is True
    assert "[Waiting for user confirmation]" in step.tool_output


def test_run_with_agents_sdk_pauses_on_interruption(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    monkeypatch.setattr(
        agents_sdk_runtime.Runner,
        "run_sync",
        lambda *a, **k: _fake_result(interruptions=[_fake_interruption()]),
    )
    result = run_with_agents_sdk(
        llm_config=_llm_config(),
        messages=[{"role": "user", "content": "删除 /tmp/x.txt"}],
        tools=[FileWriteTool()],
        working_dir=Path("/tmp"),
        max_turns=5,
    )
    assert result.pending_confirmation is not None
    assert result.pending_confirmation.tool_name == "write"
    assert result.pending_confirmation.sdk_state == "sdk-state-json"
    assert result.pending_step is not None


def test_run_with_agents_sdk_completes_without_interruption(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    monkeypatch.setattr(
        agents_sdk_runtime.Runner,
        "run_sync",
        lambda *a, **k: _fake_result(final_output="hello"),
    )
    result = run_with_agents_sdk(
        llm_config=_llm_config(),
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        working_dir=Path("/tmp"),
        max_turns=3,
    )
    assert result.pending_confirmation is None
    assert result.reply == "hello"


def test_resume_with_agents_sdk_approves_and_runs(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    pending, _ = _pending_from_interruption(
        _fake_interruption(),
        tools_by_name={"write": FileWriteTool()},
        working_dir=Path("/tmp"),
        require_confirm=None,
        sdk_state="sdk-state-json",
    )
    fake_state = SimpleNamespace(
        get_interruptions=lambda: [_fake_interruption()],
        approve=lambda item, always_approve=False: None,
    )
    monkeypatch.setattr(
        agents_sdk_runtime.RunState, "from_string", lambda agent, s: _fake_awaitable(fake_state)
    )
    monkeypatch.setattr(
        agents_sdk_runtime.Runner,
        "run",
        lambda *a, **k: _fake_awaitable(_fake_result(final_output="wrote it")),
    )
    result = agents_sdk_runtime.resume_with_agents_sdk(
        llm_config=_llm_config(),
        pending=pending,
        messages=[{"role": "user", "content": "删除 /tmp/x.txt"}],
        tools=[FileWriteTool()],
        working_dir=Path("/tmp"),
        max_turns=5,
    )
    assert result.pending_confirmation is None
    assert result.reply == "wrote it"


def test_resume_with_agents_sdk_requires_state(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    pending = PendingConfirmation(
        action_id="a",
        tool_name="write",
        arguments={"path": "/tmp/x"},
        description="d",
        risk_level="high",
        sdk_state="",
    )
    with pytest.raises(ValueError, match="sdk_state"):
        agents_sdk_runtime.resume_with_agents_sdk(
            llm_config=_llm_config(),
            pending=pending,
            messages=[],
            tools=[FileWriteTool()],
            working_dir=Path("/tmp"),
            max_turns=5,
        )


def test_pending_sdk_state_survives_session_store_roundtrip(tmp_path: Path) -> None:
    from secretary.agent.session_store import (
        pause_bundle_confirmation,
        pause_restore_confirmation,
    )

    pending = PendingConfirmation(
        action_id="act_1",
        tool_name="write",
        arguments={"path": "/tmp/x"},
        description="desc",
        risk_level="high",
        confirmation_kind="write_new",
        diff_preview="+x",
        sdk_state="RUNSTATE_JSON",
    )
    bundle = pause_bundle_confirmation(pending=pending, messages=[{"role": "user", "content": "u"}])
    restored, messages = pause_restore_confirmation(bundle)
    assert restored.sdk_state == "RUNSTATE_JSON"
    assert messages == [{"role": "user", "content": "u"}]


def _fake_awaitable(value: Any) -> Any:

    async def _wrap() -> Any:
        return value

    return _wrap()
