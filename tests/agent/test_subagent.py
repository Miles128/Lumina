"""Tests for sub-agent spawn (Phase 1: explore only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.llm_client import ChatCompletionResult, LlmToolCall
from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import AgentLoop, ListDirTool, LoopResult
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.subagent import SpawnContext, SubAgentDeps, SubAgentRunner
from secretary.agent.subagent.policy import MAX_SPAWNS_PER_TURN
from secretary.agent.subagent.registry import get_archetype, resolve_tools
from secretary.agent.subagent.spawn_tool import SpawnSubagentTool as SpawnTool
from secretary.agent.subagent.summarize import format_subagent_result
from secretary.memory.db import MemoryStore
from secretary.memory.lumina_memory import LuminaMemory


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
        memory=LuminaMemory(tmp_path),
    )


def test_explore_archetype_resolves_read_only_tools(tmp_path: Path) -> None:
    tools = resolve_tools("explore", _deps(tmp_path))
    names = {tool.name for tool in tools}
    assert "file_read" in names
    assert "search_files" in names
    assert "spawn_subagent" not in names
    assert "shell" not in names
    assert "file_write" not in names


def test_plan_sub_archetype_is_read_only(tmp_path: Path) -> None:
    tools = resolve_tools("plan", _deps(tmp_path))
    names = {tool.name for tool in tools}
    assert "list_dir" in names
    assert "spawn_subagent" not in names
    assert "file_write" not in names


def test_worker_and_verify_archetypes_exist() -> None:
    worker = get_archetype("worker")
    verify = get_archetype("verify")
    assert worker is not None and worker.name == "worker"
    assert verify is not None and verify.name == "verify"
    assert get_archetype("not-a-real-type") is None


def test_worker_includes_write_tools(tmp_path: Path) -> None:
    tools = resolve_tools("worker", _deps(tmp_path))
    names = {tool.name for tool in tools}
    assert "file_write" in names
    assert "shell" in names
    assert "spawn_subagent" not in names


def test_custom_archetype_from_lumina_dir(tmp_path: Path) -> None:
    sub_dir = tmp_path / "subagents"
    sub_dir.mkdir()
    (sub_dir / "scout.md").write_text(
        "---\nname: scout\nmax_steps: 5\ntools: list_dir,file_read,web_search\n---\n"
        "You are a scout sub-agent.\n",
        encoding="utf-8",
    )
    spec = get_archetype("scout", tmp_path)
    assert spec is not None
    assert spec.name == "scout"
    tools = resolve_tools("scout", SubAgentDeps(
        llm_config=_llm_config(),
        file_auth=None,
        memory_store=MemoryStore(tmp_path / "m.db"),
        memory=LuminaMemory(tmp_path),
        lumina_dir=tmp_path,
    ))
    assert {t.name for t in tools} == {"file_read", "list_dir", "web_search"}


def test_spawn_quota_blocks_excess_delegations(tmp_path: Path) -> None:
    runner = SubAgentRunner(_deps(tmp_path))
    context = SpawnContext(parent_session_id="sess-1", depth=0)
    context.spawns_this_turn = MAX_SPAWNS_PER_TURN
    output = runner.run_from_tool(
        {"goal": "find tests", "archetype": "explore"},
        context,
        tmp_path,
    )
    assert "quota exceeded" in output


def test_format_subagent_result_includes_summary() -> None:
    result = LoopResult(
        reply="Found handler in loop.py",
        steps=[],
        used_tools=["file_read"],
        total_steps=2,
        files_read=["loop.py"],
    )
    text = format_subagent_result(result, run_id="abc123", archetype="explore")
    assert "[subagent:explore:abc123]" in text
    assert "loop.py" in text
    assert "file_read" in text


def test_runner_explore_completes_with_mocked_child(tmp_path: Path) -> None:
    sample = tmp_path / "note.txt"
    sample.write_text("lumina subagent phase1", encoding="utf-8")

    child_result = ChatCompletionResult(
        content="Read note.txt successfully.",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "Read note.txt successfully."},
    )

    runner = SubAgentRunner(_deps(tmp_path))
    context = SpawnContext(parent_session_id="parent-1", depth=0)
    events: list[ProgressEvent] = []

    with patch(
        "secretary.agent.loop.chat_completion_with_tools",
        return_value=child_result,
    ):
        output = runner.run_from_tool(
            {
                "goal": "Read note.txt and summarize",
                "context": str(sample),
                "archetype": "explore",
            },
            context,
            tmp_path,
            progress_callback=events.append,
        )

    assert "subagent:explore:" in output
    assert context.spawns_this_turn == 1
    kinds = [event.kind for event in events]
    assert "subagent_started" in kinds
    assert "subagent_finished" in kinds


def test_parent_loop_invokes_spawn_and_receives_summary(tmp_path: Path) -> None:
    spawn_context = SpawnContext(parent_session_id="chat-1", depth=0)
    spawn_tool = SpawnTool(_deps(tmp_path), spawn_context)

    parent_spawn = ChatCompletionResult(
        content="",
        tool_calls=(
            LlmToolCall(
                id="call_spawn",
                name="spawn_subagent",
                arguments={
                    "goal": "List current directory",
                    "archetype": "explore",
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
                        "arguments": '{"goal": "List current directory", "archetype": "explore"}',
                    },
                }
            ],
        },
    )
    child_done = ChatCompletionResult(
        content="Directory contains note.txt",
        tool_calls=(),
        assistant_message={
            "role": "assistant",
            "content": "Directory contains note.txt",
        },
    )
    parent_final = ChatCompletionResult(
        content="子任务完成：目录里有 note.txt",
        tool_calls=(),
        assistant_message={"role": "assistant", "content": "子任务完成：目录里有 note.txt"},
    )

    responses = [parent_spawn, child_done, parent_final]
    events: list[ProgressEvent] = []

    loop = AgentLoop(
        _llm_config(),
        tools=[spawn_tool, ListDirTool()],
        max_steps=5,
        working_dir=tmp_path,
        progress_callback=events.append,
    )

    with (
        patch("secretary.agent.loop.requires_forced_read_tool", return_value=False),
        patch("secretary.agent.loop.should_retry_for_grounding", return_value=False),
        patch("secretary.agent.loop.should_retry_for_verification", return_value=False),
        patch(
            "secretary.agent.loop.chat_completion_with_tools",
            side_effect=responses,
        ),
    ):
        result = loop.run(
            [{"role": "user", "content": "请委派 explore 子任务列出当前目录"}],
            temperature=0.0,
        )

    assert "spawn_subagent" in result.used_tools
    assert spawn_context.spawns_this_turn == 1
    assert any(event.kind == "subagent_started" for event in events)
    assert any(event.kind == "subagent_finished" for event in events)


def test_spawn_tool_requires_goal(tmp_path: Path) -> None:
    tool = SpawnTool(_deps(tmp_path), SpawnContext(parent_session_id="s", depth=0))
    output = tool.execute({"archetype": "explore"}, tmp_path)
    assert output.error and "non-empty goal" in output.error
