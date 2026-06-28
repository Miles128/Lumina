"""Sub-agent pause/resume (Codex turn-approve semantics)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.llm_client import ChatCompletionResult, LlmToolCall
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop
from secretary.agent.subagent import SpawnContext, SubAgentDeps
from secretary.agent.subagent.spawn_tool import SpawnSubagentTool
from secretary.memory.db import MemoryStore
from secretary.memory.hermes_memory import HermesMemory


def _llm_config() -> LlmConfig:
    return LlmConfig(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
        source="env",
    )


def _deps(tmp_path: Path) -> SubAgentDeps:
    store = MemoryStore(tmp_path / "memory.db")
    return SubAgentDeps(
        llm_config=_llm_config(),
        file_auth=None,
        memory_store=store,
        hermes=HermesMemory(tmp_path),
    )


def test_worker_subagent_pauses_on_shell_then_resumes(tmp_path: Path) -> None:
    spawn_context = SpawnContext(parent_session_id="parent-1", depth=0)
    spawn_tool = SpawnSubagentTool(_deps(tmp_path), spawn_context)

    write_call = ChatCompletionResult(
        content="",
        tool_calls=(
            LlmToolCall(
                id="call_write",
                name="file_write",
                arguments={"path": "marker.txt", "content": "paused-subagent"},
            ),
        ),
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "file_write",
                        "arguments": '{"path": "marker.txt", "content": "paused-subagent"}',
                    },
                }
            ],
        },
    )
    child_done = ChatCompletionResult(
        content="Wrote marker.txt",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "Wrote marker.txt"},
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            side_effect=[write_call, child_done],
        ),
    ):
        runner = spawn_tool._runner
        outcome = runner.run_from_tool(
            {"goal": "Write marker.txt", "archetype": "worker"},
            spawn_context,
            tmp_path,
        )

    assert "等待确认" in outcome
    paused = spawn_tool.consume_paused()
    assert paused is not None
    assert paused.archetype == "worker"
    assert paused.pending.tool_name == "file_write"

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            return_value=child_done,
        ),
    ):
        summary = runner.resume_paused(paused, tmp_path)

    assert "subagent:worker:" in summary
    assert spawn_tool.consume_paused() is None


def test_parent_loop_surfaces_subagent_pause(tmp_path: Path) -> None:
    spawn_context = SpawnContext(parent_session_id="chat-1", depth=0)
    spawn_tool = SpawnSubagentTool(_deps(tmp_path), spawn_context)
    paused_holder: list[object] = []

    parent_spawn = ChatCompletionResult(
        content="",
        tool_calls=(
            LlmToolCall(
                id="call_spawn",
                name="spawn_subagent",
                arguments={
                    "goal": "Write marker.txt",
                    "archetype": "worker",
                },
            ),
        ),
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_spawn",
                    "type": "function",
                    "function": {
                        "name": "spawn_subagent",
                        "arguments": '{"goal": "Write marker.txt", "archetype": "worker"}',
                    },
                }
            ],
        },
    )
    child_write = ChatCompletionResult(
        content="",
        tool_calls=(
            LlmToolCall(
                id="call_write",
                name="file_write",
                arguments={"path": "marker.txt", "content": "test"},
            ),
        ),
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "file_write",
                        "arguments": '{"path": "marker.txt", "content": "test"}',
                    },
                }
            ],
        },
    )

    loop = AgentLoop(
        _llm_config(),
        tools=[spawn_tool],
        max_steps=3,
        working_dir=tmp_path,
        file_auth=None,
        on_subagent_paused=paused_holder.append,
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            side_effect=[parent_spawn, child_write],
        ),
    ):
        result = loop.run(
            [{"role": "user", "content": "delegate file write to worker subagent"}],
            temperature=0.0,
        )

    assert result.pending_confirmation is not None
    assert result.pending_confirmation.tool_name == "file_write"
    assert "子 Agent" in result.reply
    assert len(paused_holder) == 1
    assert paused_holder[0].archetype == "worker"


def test_resume_after_subagent_tool_continues_parent_loop(tmp_path: Path) -> None:
    spawn_tool = SpawnSubagentTool(_deps(tmp_path), SpawnContext(parent_session_id="p", depth=0))
    loop = AgentLoop(
        _llm_config(),
        tools=[spawn_tool],
        max_steps=5,
        working_dir=tmp_path,
        file_auth=None,
    )
    parent_final = ChatCompletionResult(
        content="已根据子 Agent 结果整理完毕。",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "已根据子 Agent 结果整理完毕。"},
    )
    from secretary.agent.tools.base import ToolCall

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            return_value=parent_final,
        ),
    ):
        result = loop.resume_after_subagent_tool(
            [{"role": "user", "content": "请委派 worker"}],
            thought="",
            tool_call=ToolCall(
                name="spawn_subagent",
                arguments={"goal": "write", "archetype": "worker"},
            ),
            tool_output="[subagent:worker:abc] done",
            assistant_message=None,
            native_used=False,
            step_idx=0,
            temperature=0.0,
        )

    assert "spawn_subagent" in result.used_tools
    assert "整理完毕" in result.reply
