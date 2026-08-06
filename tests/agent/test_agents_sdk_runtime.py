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


class _FakeTool:
    """Minimal Tool-shaped stub with a schema and execute."""

    def __init__(self, name: str, *, read_only: bool = False):
        self.name = name
        self.read_only = read_only
        self.risk_level = "low"

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": f"fake {self.name}",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"fake-result:{self.name}"


def test_tool_invoke_records_step_and_shell_receipt() -> None:
    from secretary.agent import agents_sdk_runtime
    from secretary.agent.tools.base import ToolCall
    from secretary.agent.tools.shell import ShellTool

    steps_out: list[Any] = []
    tracked: list[str] = []
    shell_tool = ShellTool()
    fn = agents_sdk_runtime._tool_invoke(
        shell_tool,
        "shell",
        Path("/tmp"),
        progress_callback=None,
        cancel_check=None,
        tracked=tracked,
        steps_out=steps_out,
    )
    ctx = SimpleNamespace(tool_call_id="call_sdk_1")
    out = asyncio.run(fn(ctx, '{"command": "echo hi"}'))
    assert "[receipt:call_sdk_1]" in out
    assert tracked == ["shell"]
    assert len(steps_out) == 1
    step = steps_out[0]
    assert isinstance(step.tool_call, ToolCall)
    assert step.tool_call.id == "call_sdk_1"
    assert step.tool_call.name == "shell"


def test_run_with_agents_sdk_retry_ladder_injects_web_search(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    calls: list[Any] = []

    def _fake_run(agent, input_msg, max_turns=None, run_config=None):
        calls.append(input_msg)
        if len(calls) == 1:
            # First pass: model claims search without calling tools.
            return _fake_result(final_output="让我搜一下最新数据")
        return _fake_result(final_output="基于搜索结果的回答")

    monkeypatch.setattr(agents_sdk_runtime.Runner, "run_sync", _fake_run)
    tools = [_FakeTool("web_search")]
    result = run_with_agents_sdk(
        llm_config=_llm_config(),
        messages=[{"role": "user", "content": "搜索最新 AI 新闻"}],
        tools=tools,
        working_dir=Path("/tmp"),
        max_turns=5,
    )
    assert len(calls) == 2, "web_claim 应触发第二次 run"
    assert "web_search" in result.used_tools
    injected = [m for m in calls[1] if m.get("role") == "user"]
    assert any("[Tool Result: web_search]" in str(m.get("content", "")) for m in injected)


def test_run_with_agents_sdk_steps_returned(monkeypatch) -> None:
    from secretary.agent import agents_sdk_runtime

    def _fake_run(agent, input_msg, max_turns=None, run_config=None):
        return _fake_result(final_output="ok")

    monkeypatch.setattr(agents_sdk_runtime.Runner, "run_sync", _fake_run)
    # Tracked steps only fill when tools actually execute; verify empty-safe path.
    result = run_with_agents_sdk(
        llm_config=_llm_config(),
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        working_dir=Path("/tmp"),
        max_turns=3,
    )
    assert result.steps == []
    assert result.used_tools == []
