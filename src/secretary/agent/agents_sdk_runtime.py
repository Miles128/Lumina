"""OpenAI Agents SDK backend preserving Lumina LoopResult / confirm contracts.

Replaces the legacy loop as the primary harness backend. The Agents SDK
provides native HITL (``needs_approval`` → ``interruptions`` → ``RunState``
serialization), which maps 1:1 onto Lumina's confirmation flow:

- run:         Runner.run(agent, input)            → LoopResult (or paused)
- pause:       result.to_state().to_string()       → stored in PendingConfirmation.sdk_state
- resume:      RunState.from_string(agent, s)      → approve(item) → Runner.run(agent, state)
- nested:      Agent.as_tool() approvals float to the outer run (unused v1:
               spawn_subagent keeps falling back to the legacy loop)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from agents import (
    Agent,
    AgentHooks,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelSettings,
    Runner,
    RunState,
    set_default_openai_client,
)
from agents.run import RunConfig
from agents.tool import FunctionTool
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from secretary.agent.artifact_paths import collect_artifact_paths
from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.grounding import (
    collect_command_evidence,
    collect_read_evidence,
    enforce_grounded_reply,
    resolve_turn_user_message,
    verify_reply_against_evidence,
)
from secretary.agent.harness_config import ConfirmRequireConfig
from secretary.agent.llm_config import LlmConfig, model_supports_thinking
from secretary.agent.loop import LoopResult, PendingConfirmation, StepResult
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.tools.base import Tool, ToolCall, _coerce_to_tool_result
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)


def _build_async_client(llm_config: LlmConfig) -> AsyncOpenAI:
    base = (llm_config.base_url or "").rstrip("/")
    # Network retries come from the openai SDK itself (parity with the legacy
    # outer layer's 3 attempts).
    return AsyncOpenAI(
        api_key=llm_config.api_key,
        base_url=base or None,
        max_retries=3,
    )


def _bind_default_client(llm_config: LlmConfig) -> None:
    """Point the SDK's shared OpenAI provider at Lumina's LLM config.

    Uses the Responses API by default — DeepSeek V4 supports it natively
    (api-docs.deepseek.com/guides/responses_api), which keeps reasoning
    (thought) visible, unlike the chat-completions path that strips it.
    Global but single-user: every turn overwrites with the same config.
    """
    set_default_openai_client(_build_async_client(llm_config), use_for_tracing=False)
    # Deliberately NOT calling set_default_openai_api("chat_completions"):
    # the Responses path preserves reasoning items / streaming deltas.


def _model_settings(
    llm_config: LlmConfig,
    *,
    thinking: str,
    reasoning_effort: str | None,
    temperature: float,
    strict_tools: bool = False,
) -> ModelSettings:
    """ModelSettings; DeepSeek thinking rides the Responses reasoning field."""
    from openai.types.shared import Reasoning

    settings: dict[str, Any] = {"temperature": temperature}
    if model_supports_thinking(llm_config.model):
        if thinking == "disabled":
            settings["reasoning"] = Reasoning(effort="none")
        else:
            effort: str = (
                reasoning_effort
                if reasoning_effort in {"low", "high", "max"}
                else "high"
            )
            settings["reasoning"] = Reasoning(effort=cast(Any, effort))
    return ModelSettings(**settings)


def _to_sdk_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Lumina chat-history messages (chat-completions style) into
    Responses-API input items.

    DeepSeek's Responses endpoint rejects role='tool'; tool results must be
    ``function_call_output`` items and assistant tool_calls must be expanded
    into ``function_call`` items. Old threads carry such history, so without
    this conversion every resumed conversation 400s.
    """
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": text,
                }
            )
            continue
        items.append({"type": "message", "role": role, "content": text})
        tool_calls = message.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function")
                fn_dict = fn if isinstance(fn, dict) else {}
                items.append(
                    {
                        "type": "function_call",
                        "name": str(fn_dict.get("name") or ""),
                        "arguments": str(fn_dict.get("arguments") or ""),
                        "call_id": str(call.get("id") or ""),
                    }
                )
    return items


def _with_cwd_guidance(instructions: str, working_dir: Path) -> str:
    """Append cwd context so the model resolves relative tool paths correctly."""
    cwd_line = (
        f"\n\nWorking directory (cwd): {working_dir}\n"
        "Relative tool paths (write/edit/shell/code_exec outputs) resolve against this "
        "cwd. When creating files, write them under this cwd with relative paths."
    )
    return f"{instructions}{cwd_line}"


def _split_system_and_input(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            continue
        rest.append(dict(message))
    return "\n\n".join(system_parts), rest


def _safe_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        cleaned.append(
            {"role": role, "content": content if isinstance(content, str) else ""}
        )
    return cleaned


def _pick_retry(
    reply: str,
    used_tools: list[str],
    user_message: str,
    steps: list[StepResult],
    working_dir: Path,
) -> str | None:
    """Mirror the legacy AgentLoop retry ladder.

    Returns a retry user-prompt to append, or "web_claim" (injected web_search
    execution), or None when the reply passes without another attempt.
    """
    from secretary.agent.grounding import (
        GROUNDING_RETRY_USER,
        collect_command_evidence,
        collect_read_evidence,
        has_content_grounding,
        is_file_content_question,
        should_retry_for_grounding,
        should_retry_for_verification,
        verify_reply_against_evidence,
        write_claims_unverified,
    )
    from secretary.agent.knowledge_work import (
        OFFICE_RETRY_USER,
        RESEARCH_RETRY_USER,
        should_retry_for_office,
        should_retry_for_research_intent,
    )
    from secretary.agent.web_research import (
        WEB_RETRY_USER,
        reply_claims_web_search,
        should_retry_for_web_research,
    )

    write_claim = write_claims_unverified(reply, working_dir, used_tools)
    if write_claim:
        return write_claim
    # "先看工作区/让我先…/稍等" deferral talk with tools available and
    # nothing executed → force action instead of letting the turn end.
    if _DEFER_TALK_RE.search(reply) and not used_tools:
        return "你一直在说要先查看/先做，但没有实际调用任何工具。请立即调用 ls/read/write/shell 等工具完成用户请求，不要只说要做什么。"
    # Pasting a code block without executing it is not doing the task.
    if _CODE_BLOCK_RE.search(reply) and not any(
        t in used_tools for t in ("write", "edit", "shell", "code_exec", "move")
    ):
        return "你贴出了代码但未实际生成/执行文件。请用 write 把代码写入当前工作目录并用 shell/code_exec 执行，产出真实文件。"
    if reply_claims_web_search(reply, used_tools):
        return "web_claim"
    if should_retry_for_grounding(user_message, reply, used_tools):
        if is_file_content_question(user_message) and not has_content_grounding(used_tools):
            from secretary.agent.grounding import CONTENT_GROUNDING_RETRY_USER

            return CONTENT_GROUNDING_RETRY_USER
        return GROUNDING_RETRY_USER
    if should_retry_for_web_research(user_message, reply, used_tools):
        return WEB_RETRY_USER
    if should_retry_for_research_intent(user_message, reply, used_tools):
        return RESEARCH_RETRY_USER
    if should_retry_for_office(user_message, reply, used_tools):
        return OFFICE_RETRY_USER
    evidence = collect_read_evidence(steps)
    command_evidence = collect_command_evidence(steps)
    verification = verify_reply_against_evidence(
        reply,
        evidence,
        user_message,
        command_evidence=command_evidence,
    )
    if should_retry_for_verification(verification):
        from secretary.agent.grounding import format_verify_retry

        return format_verify_retry(
            verification, evidence, command_evidence=command_evidence
        )
    return None


def _tool_invoke(
    tool: Tool,
    tool_name: str,
    working_dir: Path,
    *,
    progress_callback: Callable[[ProgressEvent], None] | None,
    cancel_check: Callable[[], bool] | None,
    tracked: list[str],
    steps_out: list[StepResult],
) -> Callable[[Any, str], Awaitable[str]]:
    async def _invoke(ctx: Any, arguments: str) -> str:
        if cancel_check is not None and cancel_check():
            raise RuntimeError("cancelled")
        if hasattr(tool, "bind_progress"):
            tool.bind_progress(progress_callback)
        if hasattr(tool, "bind_cancel_check"):
            tool.bind_cancel_check(cancel_check)
        if progress_callback is not None:
            progress_callback(
                ProgressEvent(
                    kind="tool_started",
                    iteration=len(tracked) + 1,
                    tool_name=tool_name,
                )
            )
        args_dict = _parse_tool_arguments(arguments)
        try:
            raw = tool.execute(args_dict, working_dir)
            text = _coerce_to_tool_result(raw, tool_name=tool_name).to_output_string()
        except Exception as exc:
            text = f"Error executing {tool_name}: {exc}"
            logger.warning("agents-sdk tool %s failed: %s", tool_name, exc)
            if progress_callback is not None:
                progress_callback(
                    ProgressEvent(
                        kind="tool_finished",
                        iteration=len(tracked) + 1,
                        tool_name=tool_name,
                        success=False,
                        message=text,
                    )
                )
            raise
        tracked.append(tool_name)
        ok = not text.startswith("Error")
        # Shell receipt: citeable command evidence for grounding verification.
        call_id = str(getattr(ctx, "tool_call_id", "") or "").strip() or f"{tool_name}_{len(tracked)}"
        if tool_name == "shell" and ok:
            text = f"[receipt:{call_id}]\n{text}"
        steps_out.append(
            StepResult(
                thought="",
                tool_call=ToolCall(name=tool_name, arguments=args_dict, id=call_id),
                tool_output=text,
            )
        )
        if progress_callback is not None:
            progress_callback(
                ProgressEvent(
                    kind="tool_finished",
                    iteration=len(tracked),
                    tool_name=tool_name,
                    success=ok,
                    detail=text[:500],
                    paths=tuple(
                        collect_artifact_paths(
                            tool_name,
                            args_dict,
                            working_dir,
                            output=text,
                            success=ok,
                        )
                    ),
                )
            )
        return text

    return _invoke


def _parse_tool_arguments(arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return dict(arguments)
    try:
        parsed = json.loads(arguments or "{}")
    except (ValueError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _make_approval(
    name: str,
    needs_confirm: Callable[[str, dict[str, Any]], bool],
) -> Callable[[Any, dict[str, Any], str], Awaitable[bool]]:
    async def _needs_approval(
        ctx: Any, arguments: dict[str, Any], call_id: str
    ) -> bool:
        del ctx, call_id
        return needs_confirm(name, dict(arguments or {}))

    return _needs_approval


# ---------------------------------------------------------------------------
# Sub-agent delegation (Phase 2): one static Agent.as_tool per archetype.
# The tool carries goal/context/criteria params; nested tool approvals float
# to the outer run's interruptions (SDK native).
# ---------------------------------------------------------------------------

class SpawnParams(BaseModel):
    """Tool arguments for spawning a sub-agent of one archetype."""

    goal: str = Field(..., description="Clear, self-contained task for the sub-agent.")
    context: str = Field(default="", description="Optional paths, constraints, or facts.")
    success_criteria: str = Field(
        default="",
        description="Optional machine-verifiable acceptance criteria (verify archetype).",
    )


def _subagent_input_builder(options: Any) -> list[dict[str, Any]]:
    params = options.get("params") or {}
    parts = [f"任务目标：{str(params.get('goal') or '').strip()}"]
    context = str(params.get("context") or "").strip()
    if context:
        parts.append(f"背景/约束：{context}")
    criteria = str(params.get("success_criteria") or "").strip()
    if criteria:
        parts.append(f"验收标准：{criteria}")
    return [{"role": "user", "content": "\n\n".join(parts)}]


def _agent_result_text(result: Any) -> str:
    """Extract the final text output from an SDK RunResult (mirrors as_tool default)."""
    out = getattr(result, "final_output", None)
    if isinstance(out, str) and out.strip():
        return out.strip()
    from agents.items import ItemHelpers, MessageOutputItem

    for item in reversed(getattr(result, "new_items", None) or []):
        if isinstance(item, MessageOutputItem):
            text = ItemHelpers.text_message_output(item)
            if text:
                return text
    return str(out or "").strip()


_PARALLEL_EXPLORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goals": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 3,
            "description": "2-3 independent read-only explore goals to run in parallel.",
        }
    },
    "required": ["goals"],
    "additionalProperties": False,
}


def _parallel_explore_invoke(
    explore_agent: Agent,
    max_turns: int,
    *,
    cancel_check: Callable[[], bool] | None,
    budget: list[int],
) -> Callable[[Any, str], Awaitable[str]]:
    """Invoke handler for spawn_explore_parallel: run N explore goals concurrently.

    ``budget`` is a shared per-turn counter (MAX_PARALLEL_EXPLORE) so repeated
    parallel calls cannot exceed the fan-out quota within one turn.
    """
    run_config = RunConfig(tracing_disabled=True)

    async def run_one(goal: str) -> str:
        if cancel_check is not None and cancel_check():
            return f"[cancelled] {goal}"
        try:
            result = await Runner.run(
                starting_agent=explore_agent,
                input=[{"role": "user", "content": goal}],
                max_turns=max_turns,
                run_config=run_config,
            )
        except MaxTurnsExceeded:
            return f"[max_turns exceeded] {goal}"
        except Exception as exc:
            logger.warning("parallel explore goal failed: %s", exc)
            return f"[error] {goal}: {exc}"
        text = _agent_result_text(result)
        return text or f"[no output] {goal}"

    async def _invoke(ctx: Any, arguments: str) -> str:
        del ctx
        args = _parse_tool_arguments(arguments)
        raw_goals = args.get("goals") or []
        goals = [str(g).strip() for g in raw_goals if str(g).strip()][:3]
        if len(goals) < 2:
            return "Error: spawn_explore_parallel requires 2-3 non-empty goals."
        remaining = budget[0]
        if remaining <= 0:
            from secretary.agent.subagent.policy import MAX_PARALLEL_EXPLORE

            return f"Error: 并行 explore 配额已用完（本轮最多 {MAX_PARALLEL_EXPLORE} 个并行目标）。"
        goals = goals[:remaining]
        budget[0] = remaining - len(goals)
        results = await asyncio.gather(*(run_one(g) for g in goals))
        return "\n\n".join(
            f"### explore {index}: {goal}\n{text}"
            for index, (goal, text) in enumerate(zip(goals, results, strict=False), 1)
        )

    return _invoke



def _strip_reasoning_xml(text: str) -> str:
    """Strip tool-call XML residue the model mimics inside reasoning.

    DeepSeek's training data includes Claude-Code/OpenClaw style tool-call
    envelopes (<antml:invoke>/<antml:parameter>/</invoke>…); the model often
    echoes them while thinking. They are noise for the user-facing thought
    display, so drop any <...> tags and squeeze blank lines.
    """
    import re as _re

    cleaned = _re.sub(r"<[^>]*>", "", text)
    cleaned = _re.sub(r"[ \t]+", " ", cleaned)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class _LuminaHooks(AgentHooks[Any]):
    """Parent-run hooks: record spawn_* as_tool calls and surface reasoning.

    The Responses API keeps reasoning items in the model output, so the
    model's thought process can be shown again (legacy had it via streaming).
    """

    def __init__(
        self,
        tracked: list[str],
        progress_callback: Callable[[ProgressEvent], None] | None,
    ) -> None:
        self._tracked = tracked
        self._progress_callback = progress_callback

    async def on_tool_start(
        self,
        context: Any,
        agent: Any,
        tool: Any,
    ) -> None:
        tool_name = str(getattr(context, "tool_name", "") or "")
        if tool_name.startswith("spawn_") and tool_name not in self._tracked:
            self._tracked.append(tool_name)
            return
        # SDK built-in tools (e.g. Responses server-side web_search) bypass our
        # wrappers; surface them as progress events for the UI.
        if tool_name == "web_search" and tool_name not in self._tracked:
            self._tracked.append(tool_name)
            if self._progress_callback is not None:
                self._progress_callback(
                    ProgressEvent(kind="tool_started", iteration=0, tool_name=tool_name)
                )
                self._progress_callback(
                    ProgressEvent(
                        kind="tool_finished", iteration=0, tool_name=tool_name, success=True
                    )
                )

    async def on_llm_end(
        self,
        context: Any,
        agent: Any,
        response: Any,
    ) -> None:
        if self._progress_callback is None:
            return
        thoughts: list[str] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", "") != "reasoning":
                continue
            d: dict[str, Any] = getattr(item, "model_dump", lambda: {})()
            text = d.get("summary") or d.get("content") or ""
            if isinstance(text, list):
                text = "".join(
                    str(part.get("text", ""))
                    for part in text
                    if isinstance(part, dict)
                )
            text = _strip_reasoning_xml(str(text))
            if text:
                thoughts.append(text)
        if thoughts:
            self._progress_callback(
                ProgressEvent(
                    kind="thought",
                    iteration=0,
                    message="\n\n".join(thoughts)[:2000],
                )
            )


class _SubagentHooks(AgentHooks[Any]):
    """Progress events for the sub-agent lane (archetype-scoped)."""

    def __init__(
        self,
        archetype: str,
        progress_callback: Callable[[ProgressEvent], None] | None,
    ) -> None:
        self._archetype = archetype
        self._progress_callback = progress_callback

    async def on_start(self, context: Any, agent: Any) -> None:
        if self._progress_callback is not None:
            self._progress_callback(
                ProgressEvent(
                    kind="subagent_started",
                    iteration=0,
                    message=f"正在派生子 Agent（{self._archetype}）",
                    archetype=self._archetype,
                    subagent_status="running",
                )
            )

    async def on_end(self, context: Any, agent: Any, agent_input: Any = None, agent_output: Any = None) -> None:
        if self._progress_callback is not None:
            self._progress_callback(
                ProgressEvent(
                    kind="subagent_finished",
                    iteration=0,
                    message=f"子 Agent（{self._archetype}）已完成",
                    archetype=self._archetype,
                    subagent_status="completed",
                )
            )


def build_subagent_tools(
    *,
    llm_config: LlmConfig,
    tools_by_name: dict[str, Tool],
    working_dir: Path,
    needs_confirm: Callable[[str, dict[str, Any]], bool],
    progress_callback: Callable[[ProgressEvent], None] | None,
    cancel_check: Callable[[], bool] | None,
    strict_tools: bool,
    thinking: str,
    reasoning_effort: str | None,
    temperature: float,
    lumina_dir: Path | None,
    archetypes: tuple[str, ...] | None = None,
    tracked: list[str] | None = None,
    steps_out: list[StepResult] | None = None,
) -> list[FunctionTool]:
    """Build one ``spawn_{archetype}`` as_tool per archetype.

    Each sub-agent gets the archetype system prompt, its tool allowlist, the
    same confirm policy (nested approvals float to the outer run), and its own
    max_turns ceiling. Tool usage is recorded into the shared ``tracked`` /
    ``steps_out`` lists (outer run view).
    """
    from secretary.agent.subagent.policy import MAX_PARALLEL_EXPLORE
    from secretary.agent.subagent.registry import get_archetype, list_archetype_names

    names = archetypes or tuple(list_archetype_names(lumina_dir))
    wrapped: list[FunctionTool] = []
    shared_tracked = tracked if tracked is not None else []
    shared_steps = steps_out if steps_out is not None else []
    # Per-turn fan-out quota: repeated spawn_explore_parallel calls within one
    # turn share this counter, so the model cannot exceed MAX_PARALLEL_EXPLORE
    # concurrent explore goals (mirrors the legacy SubAgentRunner quota).
    parallel_budget = [MAX_PARALLEL_EXPLORE]
    for archetype in names:
        spec = get_archetype(archetype, lumina_dir)
        if spec is None:
            continue
        sub_tools = [
            tools_by_name[name]
            for name in (spec.tool_names or ())
            if name in tools_by_name
        ]
        tracked = shared_tracked
        steps_out = shared_steps
        agent = Agent(
            name=f"lumina-{archetype}",
            model=llm_config.model,
            instructions=spec.system_prompt,
            tools=cast(Any, wrap_lumina_tools(
                sub_tools,
                working_dir,
                needs_confirm=needs_confirm,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                tracked=tracked,
                steps_out=steps_out,
                strict_tools=strict_tools,
            )),
            model_settings=_model_settings(
                llm_config,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                strict_tools=strict_tools,
            ),
            hooks=_SubagentHooks(archetype, progress_callback),
        )
        wrapped.append(
            agent.as_tool(
                tool_name=f"spawn_{archetype}",
                tool_description=(
                    f"Delegate a {archetype} sub-task to an isolated sub-agent. "
                    "The sub-agent only has a restricted tool set and returns a "
                    "summary. `goal` is required."
                ),
                parameters=SpawnParams,
                input_builder=cast(Any, _subagent_input_builder),
                max_turns=spec.max_steps,
            )
        )
        if archetype == "explore":
            wrapped.append(
                FunctionTool(
                    name="spawn_explore_parallel",
                    description=(
                        "Run 2-3 independent read-only explore goals in parallel. "
                        "Use for fanning out independent research/lookup tasks; "
                        "each goal returns its own summary."
                    ),
                    params_json_schema=_PARALLEL_EXPLORE_SCHEMA,
                    on_invoke_tool=_parallel_explore_invoke(
                        agent,
                        spec.max_steps,
                        cancel_check=cancel_check,
                        budget=parallel_budget,
                    ),
                )
            )
    return wrapped


def wrap_lumina_tools(
    tools: list[Tool],
    working_dir: Path,
    *,
    needs_confirm: Callable[[str, dict[str, Any]], bool],
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    tracked: list[str] | None = None,
    steps_out: list[StepResult] | None = None,
    strict_tools: bool = False,
) -> list[FunctionTool]:
    """Convert Lumina Tool objects into Agents SDK FunctionTool."""
    used = tracked if tracked is not None else []
    used_steps = steps_out if steps_out is not None else []
    wrapped: list[FunctionTool] = []
    for tool in tools:
        schema = tool.schema() if hasattr(tool, "schema") else {}
        name = str(schema.get("name") or getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        description = str(schema.get("description") or "")
        parameters = schema.get("parameters") if isinstance(schema.get("parameters"), dict) else {}

        wrapped.append(
            FunctionTool(
                name=name,
                description=description,
                params_json_schema=cast(dict[str, Any], parameters),
                on_invoke_tool=_tool_invoke(
                    tool,
                    name,
                    working_dir,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    tracked=used,
                    steps_out=used_steps,
                ),
                strict_json_schema=strict_tools,
                needs_approval=_make_approval(name, needs_confirm),
            )
        )
    return wrapped


def _build_agent(
    llm_config: LlmConfig,
    *,
    instructions: str,
    tools: list[FunctionTool],
    model_settings: ModelSettings,
    hooks: AgentHooks[Any] | None = None,
) -> Agent:
    return Agent(
        name="lumina",
        model=llm_config.model,
        instructions=instructions or None,
        tools=cast(Any, tools),
        model_settings=model_settings,
        hooks=hooks,
    )


def _pending_from_interruption(
    interruption: Any,
    *,
    tools_by_name: dict[str, Tool],
    working_dir: Path,
    require_confirm: ConfirmRequireConfig | None,
    sdk_state: str,
) -> tuple[PendingConfirmation, StepResult]:
    tool_name = str(getattr(interruption, "name", "") or "")
    arguments = _parse_tool_arguments(getattr(interruption, "arguments", None) or {})
    tool = tools_by_name.get(tool_name)
    if tool is not None:
        description = tool.describe_action(arguments, working_dir)
        risk = tool.risk_level
        _, kind = tool_requires_confirmation(
            tool,
            arguments,
            working_dir=working_dir,
            file_auth=None,
            require_confirm=require_confirm,
        )
    else:
        description = f"{tool_name} 需要你的确认"
        risk = "high"
        kind = "action"
    from secretary.agent.tools.edit_text import build_confirm_diff_preview

    pending = PendingConfirmation(
        action_id=f"act_{datetime.now(UTC).strftime('%H%M%S')}_{uuid4().hex[:6]}",
        tool_name=tool_name,
        arguments=arguments,
        description=description,
        risk_level=risk,
        confirmation_kind=kind or "action",
        diff_preview=build_confirm_diff_preview(tool_name, arguments, working_dir),
        sdk_state=sdk_state,
    )
    step = StepResult(
        thought="",
        tool_call=None,
        tool_output=f"[Waiting for user confirmation] {description}",
        needs_confirmation=True,
    )
    return pending, step


def _emit_stream_event(
    ev: Any,
    progress_callback: Callable[[ProgressEvent], None] | None,
    thought_buffer: list[str] | None,
) -> None:
    """Forward Responses stream deltas: output text → reply_delta (typewriter),
    reasoning deltas accumulated for one thought event at turn end."""
    data = getattr(ev, "data", None)
    if data is None:
        return
    d = data if isinstance(data, dict) else getattr(data, "model_dump", lambda: {})()
    etype = str(d.get("type", ""))
    delta = d.get("delta")
    if etype == "response.output_text.delta" and isinstance(delta, str) and delta:
        if progress_callback is not None:
            progress_callback(ProgressEvent(kind="reply_delta", iteration=0, message=delta))
    elif etype == "response.reasoning_text.delta" and isinstance(delta, str) and delta:
        if thought_buffer is not None:
            thought_buffer.append(delta)


_DEFER_TALK_RE = re.compile(
    r"(?:先看|先看看|让我先|我先|稍等|等我看|先确认|先建|先做(?:一下|个)?工作|看一下|看下|先浏览|先探索|先检查|先查)",
)
_CODE_BLOCK_RE = re.compile(r"```[\w+]*\s*\n", re.IGNORECASE)


class _MissingToolResult:
    """Sentinel returned when the model referenced a tool outside its set."""

    def __init__(self, error: str) -> None:
        self.error = error


def _missing_tool_name(error: str) -> str:
    """Extract the tool name from 'Tool X not found in agent Y' style errors."""
    import re as _re

    match = _re.search(r"Tool ([\w.]+) not found", error or "")
    if match:
        return match.group(1)
    return ""


def _run_streamed_turn(
    agent: Agent,
    input_messages: Any,
    max_turns: int,
    progress_callback: Callable[[ProgressEvent], None] | None,
    thought_buffer: list[str],
) -> Any:
    """Run one SDK turn via run_streamed, forwarding deltas as events."""

    async def _go() -> Any:
        try:
            streamed = Runner.run_streamed(
                agent,
                cast(Any, input_messages),
                max_turns=max_turns,
                run_config=RunConfig(tracing_disabled=True),
            )
            async for ev in streamed.stream_events():
                _emit_stream_event(ev, progress_callback, thought_buffer)
            return streamed
        except ModelBehaviorError as exc:
            # The model called a tool that is not in its toolset (e.g. profile
            # routing picked read-only tools but instructions hinted at write).
            # Surface as a recoverable marker instead of killing the turn.
            logger.warning("agents-sdk model behavior error: %s", exc)
            return _MissingToolResult(str(exc))

    return asyncio.run(_go())


def run_with_agents_sdk(
    *,
    llm_config: LlmConfig,
    messages: list[dict[str, Any]],
    tools: list[Tool],
    working_dir: Path,
    max_turns: int,
    temperature: float = 0.7,
    thinking: str = "enabled",
    reasoning_effort: str | None = "high",
    strict_tools: bool = False,
    file_auth: FileAuthService | None = None,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    explicit_working_dir: bool = False,
    require_confirm: ConfirmRequireConfig | None = None,
    compaction_max_tokens: int | None = None,
    compaction_keep_tail: int | None = None,
    lumina_dir: Path | None = None,
    web_search_backend: str = "tavily",
    full_tools: list[Tool] | None = None,
    allow_mode_upgrade: bool = True,
) -> LoopResult:
    """Run one Agents SDK turn and map to LoopResult (HITL + grounding)."""
    _bind_default_client(llm_config)
    # The dynamic spawn_subagent tool is replaced by per-archetype as_tools on
    # this backend (nested approvals float to the outer run).
    parent_tools = [t for t in tools if getattr(t, "name", "") != "spawn_subagent"]
    # DeepSeek server-side search: swap Lumina's Tavily tool for the SDK's
    # built-in web_search (executed by the Responses API provider).
    extra_tools: list[Any] = []
    if web_search_backend == "responses":
        from agents.tool import WebSearchTool

        parent_tools = [
            t for t in parent_tools if getattr(t, "name", "") != "web_search"
        ]
        extra_tools.append(WebSearchTool())
    tools_by_name = {t.name: t for t in parent_tools if getattr(t, "name", "")}
    tracked: list[str] = []
    tracked_steps: list[StepResult] = []
    run_messages = list(messages)

    if explicit_working_dir:
        list_tool = tools_by_name.get("list_dir")
        if list_tool is not None:
            try:
                listing = _coerce_to_tool_result(
                    list_tool.execute({"path": "."}, working_dir),
                    tool_name="list_dir",
                ).to_output_string()
                tracked.append("list_dir")
                run_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[Workspace preflight list_dir for `{working_dir}`]\n{listing}"
                        ),
                    }
                )
            except Exception as exc:
                logger.warning("agents-sdk workspace preflight list_dir failed: %s", exc)

    # FR-52: honor harness compaction budget (one-shot before the Runner).
    compaction_kwargs: dict[str, Any] = {}
    if compaction_max_tokens is not None:
        compaction_kwargs["max_tokens"] = compaction_max_tokens
    if compaction_keep_tail is not None:
        compaction_kwargs["keep_tail"] = compaction_keep_tail
    if compaction_kwargs:
        from secretary.agent.context_compaction import compact_messages_if_needed

        compaction = compact_messages_if_needed(
            run_messages, llm_config, **compaction_kwargs
        )
        if compaction.triggered:
            run_messages = compaction.messages
            if progress_callback is not None:
                progress_callback(
                    ProgressEvent(
                        kind="context_compacted",
                        iteration=0,
                        message=(
                            f"上下文已压缩：{compaction.before_tokens}→"
                            f"{compaction.after_tokens} tokens ({compaction.mode})"
                        ),
                        detail=compaction.to_detail(),
                        prompt_tokens=compaction.before_tokens,
                        completion_tokens=compaction.after_tokens,
                    )
                )

    def _needs_confirm(tool_name: str, arguments: dict[str, Any]) -> bool:
        tool = tools_by_name.get(tool_name)
        if tool is None:
            return False
        needs, _kind = tool_requires_confirmation(
            tool,
            arguments,
            working_dir=working_dir,
            file_auth=file_auth,
            require_confirm=require_confirm,
        )
        return needs

    instructions, input_messages = _split_system_and_input(run_messages)
    instructions = _with_cwd_guidance(instructions, working_dir)
    instructions += (
        "\n\nPython 工作流：当任务需要运行 Python 生成文件（图表/Excel/文本等）时，"
        "1) 先用 write 把脚本写入当前工作目录；2) 再用 shell/code_exec 执行它；"
        "3) 所有产物（图片/Excel/CSV/日志等）必须保存到当前工作目录（沙箱或工作区）；"
        "4) 回复时用绝对路径明确列出每个产物文件。不要声称生成而未实际落盘。"
    )
    if web_search_backend == "responses":
        instructions += (
            "\n\n你有内置 web_search 工具（服务端联网搜索）。用户请求实时信息、"
            "天气、新闻、行情、网络数据时必须调用 web_search 获取真实结果，"
            "不要声称无法联网。"
        )

    def _build_agent_for(tool_set: list[Tool]) -> Agent:
        """Build the agent for a given parent tool set (rebuildable on mode upgrade)."""
        set_by_name = {t.name: t for t in tool_set if getattr(t, "name", "")}
        subagent_tools: list[FunctionTool] = []
        if lumina_dir is not None:
            subagent_tools = build_subagent_tools(
                llm_config=llm_config,
                tools_by_name=set_by_name,
                working_dir=working_dir,
                needs_confirm=_needs_confirm,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                strict_tools=strict_tools,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                lumina_dir=lumina_dir,
                tracked=tracked,
                steps_out=tracked_steps,
            )
        return _build_agent(
            llm_config,
            instructions=instructions,
            hooks=_LuminaHooks(tracked, progress_callback),
            tools=[
                *wrap_lumina_tools(
                    tool_set,
                    working_dir,
                    needs_confirm=_needs_confirm,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    tracked=tracked,
                    steps_out=tracked_steps,
                    strict_tools=strict_tools,
                ),
                *subagent_tools,
                *extra_tools,
            ],
            model_settings=_model_settings(
                llm_config,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                strict_tools=strict_tools,
            ),
        )

    agent = _build_agent_for(parent_tools)
    # Retry ladder mirroring the legacy AgentLoop (shared budget): the model
    # often *claims* it searched / verified without calling a tool; give it a
    # chance to ground the answer instead of ending the turn unverified.
    max_shared_retries = 3
    shared_retries = 0
    final_reply = ""
    verified = True
    note = ""
    while True:
        current_input = _to_sdk_input(_split_system_and_input(run_messages)[1])
        turn_thoughts: list[str] = []
        try:
            result = _run_streamed_turn(
                agent,
                current_input if current_input else run_messages,
                max_turns,
                progress_callback,
                turn_thoughts,
            )
        except MaxTurnsExceeded:
            logger.warning("agents-sdk run exceeded turn budget")
            final_reply = "已用完工具轮次上限，无法继续执行。请重新发起请求或降低任务复杂度。"
            user_message = resolve_turn_user_message(_safe_messages(run_messages))
            final_reply, verified, note = enforce_grounded_reply(
                final_reply, user_message, tracked,
                grounding_verified=True, grounding_note="",
            )
            return LoopResult(
                reply=final_reply,
                steps=tracked_steps,
                used_tools=tracked,
                total_steps=len(tracked) or 1,
                grounding_verified=verified,
                grounding_note=note,
            )

        interruptions = getattr(result, "interruptions", None) or []
        if interruptions:
            first = interruptions[0]
            sdk_state = result.to_state().to_string()
            pending, step = _pending_from_interruption(
                first,
                tools_by_name=tools_by_name,
                working_dir=working_dir,
                require_confirm=require_confirm,
                sdk_state=sdk_state,
            )
            return LoopResult(
                reply=f"我需要你的确认才能继续：\n\n{pending.description}\n\n是否允许？",
                steps=[step],
                used_tools=tracked,
                total_steps=len(tracked) or 1,
                pending_confirmation=pending,
                pending_step=step,
                messages_snapshot=_safe_messages(run_messages),
            )

        if isinstance(result, _MissingToolResult):
            if shared_retries >= max_shared_retries:
                return LoopResult(
                    reply="模型调用了当前模式下不可用的工具，多次重试后仍失败。请切换到 Build 模式重试。",
                    steps=tracked_steps,
                    used_tools=tracked,
                    total_steps=len(tracked) or 1,
                )
            shared_retries += 1
            missing = _missing_tool_name(result.error)
            upgraded = False
            if (
                allow_mode_upgrade
                and full_tools
                and missing
                and missing not in {getattr(t, "name", "") for t in parent_tools}
                and any(getattr(t, "name", "") == missing for t in full_tools)
            ):
                # The routed profile lacks a tool the model legitimately needs
                # (e.g. write under ASK) — upgrade to the full Build tool set.
                parent_tools = [
                    t for t in full_tools if getattr(t, "name", "") != "spawn_subagent"
                ]
                tools_by_name = {t.name: t for t in parent_tools}
                agent = _build_agent_for(parent_tools)
                upgraded = True
            run_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"你上一步调用了不可用的工具（{result.error}）。"
                        + (
                            "已自动切换到完整工具模式，现在可用 write/edit/shell/code_exec 等全部工具，请继续完成。"
                            if upgraded
                            else (
                                f"当前可用工具：{', '.join(sorted({getattr(t, 'name', '') for t in parent_tools}))}。"
                                "请只用可用工具完成用户请求。"
                            )
                        )
                    ),
                }
            )
            continue

        reply = getattr(result, "final_output", None)
        final_reply = reply if isinstance(reply, str) else ("" if reply is None else str(reply))
        safe_messages = _safe_messages(run_messages)
        user_message = resolve_turn_user_message(safe_messages)
        if turn_thoughts and progress_callback is not None:
            progress_callback(
                ProgressEvent(
                    kind="thought",
                    iteration=0,
                    message=_strip_reasoning_xml("\n\n".join(turn_thoughts))[:2000],
                )
            )

        if not final_reply.strip():
            # Empty model output (occasional DeepSeek thinking-mode quirk):
            # ask once more with thinking disabled rather than returning blank.
            if shared_retries >= max_shared_retries:
                break
            shared_retries += 1
            run_messages.append(
                {
                    "role": "user",
                    "content": "你上一步没有返回任何内容。请重新回答用户的问题。",
                }
            )
            continue

        if shared_retries >= max_shared_retries:
            break

        retry_kind = _pick_retry(
            final_reply,
            tracked,
            user_message,
            tracked_steps,
            working_dir,
        )
        if retry_kind is None:
            break
        shared_retries += 1
        if retry_kind == "web_claim":
            # Guide the model to actually call web_search (the SDK built-in
            # tool executes server-side and cannot be invoked manually).
            if web_search_backend == "responses":
                run_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你上一轮声称要联网但没有实际调用 web_search 工具。"
                            "请立即调用 web_search 搜索：「"
                            + user_message.strip()[:120]
                            + "」，把真实结果整理后回复用户。"
                        ),
                    }
                )
            else:
                web_tool = tools_by_name.get("web_search")
                if web_tool is None:
                    break
                try:
                    output = _coerce_to_tool_result(
                        web_tool.execute(
                            {"query": user_message.strip()[:200]}, working_dir
                        ),
                        tool_name="web_search",
                    ).to_output_string()
                except Exception as exc:
                    logger.warning("agents-sdk injected web_search failed: %s", exc)
                    break
                tracked.append("web_search")
                tracked_steps.append(
                    StepResult(
                        thought="",
                        tool_call=ToolCall(
                            name="web_search",
                            arguments={"query": user_message.strip()[:200]},
                            id=f"call_auto_web_search_{shared_retries}",
                        ),
                        tool_output=output,
                    )
                )
                run_messages.append(
                    {
                        "role": "user",
                        "content": f"[Tool Result: web_search]\n{output}",
                    }
                )
        else:
            run_messages.append({"role": "assistant", "content": final_reply})
            run_messages.append({"role": "user", "content": retry_kind})
        continue

    evidence = collect_read_evidence(tracked_steps)
    command_evidence = collect_command_evidence(tracked_steps)
    verification = verify_reply_against_evidence(
        final_reply,
        evidence,
        user_message,
        command_evidence=command_evidence,
    )
    if not final_reply.strip():
        final_reply = "模型未返回任何内容，请重试或换个说法。"
    final_reply, verified, note = enforce_grounded_reply(
        final_reply,
        user_message,
        tracked,
        grounding_verified=verification.ok,
        grounding_note=verification.note,
        command_evidence=command_evidence,
    )
    return LoopResult(
        reply=final_reply,
        steps=tracked_steps,
        used_tools=tracked,
        total_steps=len(tracked) or 1,
        grounding_verified=verified,
        grounding_note=note,
    )


def resume_with_agents_sdk(
    *,
    llm_config: LlmConfig,
    pending: PendingConfirmation,
    messages: list[dict[str, Any]],
    tools: list[Tool],
    working_dir: Path,
    max_turns: int,
    temperature: float = 0.7,
    thinking: str = "enabled",
    reasoning_effort: str | None = "high",
    strict_tools: bool = False,
    file_auth: FileAuthService | None = None,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    require_confirm: ConfirmRequireConfig | None = None,
    lumina_dir: Path | None = None,
    web_search_backend: str = "tavily",
    full_tools: list[Tool] | None = None,
    allow_mode_upgrade: bool = True,
) -> LoopResult:
    """Approve a paused SDK interruption (RunState round-trip) and continue.

    ``messages`` is the pause-time conversation snapshot used to rebuild the
    agent (instructions + tools) for ``RunState.from_string``, which requires
    the original top-level agent definition (including any as_tool sub-agents).
    """
    sdk_state = str(getattr(pending, "sdk_state", "") or "")
    if not sdk_state:
        raise ValueError("resume_with_agents_sdk requires PendingConfirmation.sdk_state")

    _bind_default_client(llm_config)
    tools_by_name = {t.name: t for t in tools if getattr(t, "name", "")}
    tracked: list[str] = []
    tracked_steps: list[StepResult] = []

    def _needs_confirm(tool_name: str, arguments: dict[str, Any]) -> bool:
        tool = tools_by_name.get(tool_name)
        if tool is None:
            return False
        needs, _kind = tool_requires_confirmation(
            tool,
            arguments,
            working_dir=working_dir,
            file_auth=file_auth,
            require_confirm=require_confirm,
        )
        return needs

    # Calls the user already approved during a previous pause must not re-trigger
    # confirmation when the resumed model re-issues the same call (fresh call_id
    # would otherwise fail the needs_approval check again → double confirmation).
    approved_calls: set[tuple[str, str]] = set()

    def _needs_confirm_resume(tool_name: str, arguments: dict[str, Any]) -> bool:
        key = (tool_name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if key in approved_calls:
            return False
        return _needs_confirm(tool_name, arguments)

    async def _resume() -> LoopResult:
        instructions, input_messages = _split_system_and_input(messages)
        instructions = _with_cwd_guidance(instructions, working_dir)
        if web_search_backend == "responses":
            instructions += (
                "\n\n你有内置 web_search 工具（服务端联网搜索）。用户请求实时信息、"
                "天气、新闻、行情、网络数据时必须调用 web_search 获取真实结果，"
                "不要声称无法联网。"
            )
        parent_tools = [t for t in tools if getattr(t, "name", "") != "spawn_subagent"]
        extra_tools: list[Any] = []
        if web_search_backend == "responses":
            from agents.tool import WebSearchTool

            parent_tools = [
                t for t in parent_tools if getattr(t, "name", "") != "web_search"
            ]
            extra_tools.append(WebSearchTool())
        parent_by_name = {t.name: t for t in parent_tools}
        subagent_tools: list[FunctionTool] = []
        if lumina_dir is not None:
            subagent_tools = build_subagent_tools(
                llm_config=llm_config,
                tools_by_name=parent_by_name,
                working_dir=working_dir,
                needs_confirm=_needs_confirm,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                strict_tools=strict_tools,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                lumina_dir=lumina_dir,
                tracked=tracked,
                steps_out=tracked_steps,
            )
        agent = _build_agent(
            llm_config,
            instructions=instructions,
            hooks=_LuminaHooks(tracked, progress_callback),
            tools=[
                *wrap_lumina_tools(
                    parent_tools,
                    working_dir,
                    needs_confirm=_needs_confirm_resume,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    tracked=tracked,
                    steps_out=tracked_steps,
                    strict_tools=strict_tools,
                ),
                *subagent_tools,
                *extra_tools,
            ],
            model_settings=_model_settings(
                llm_config,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                temperature=temperature,
                strict_tools=strict_tools,
            ),
        )
        state = await RunState.from_string(agent, sdk_state)
        approved = False
        for item in state.get_interruptions():
            if str(getattr(item, "name", "") or "") == pending.tool_name:
                state.approve(item, always_approve=True)
                approved = True
                approved_calls.add(
                    (
                        str(getattr(item, "name", "") or ""),
                        json.dumps(
                            _parse_tool_arguments(getattr(item, "arguments", None) or {}),
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                    )
                )
        if not approved:
            raise ValueError(f"paused interruption {pending.tool_name} not found in state")
        # The SDK counts max_turns against the FULL run (current_turn resumes
        # from the restored state), so hand it the used turns plus the fresh
        # per-turn budget — otherwise a turn that nearly exhausted its budget
        # before pausing dies with MaxTurnsExceeded right after resume.
        used_turns = int(getattr(state, "_current_turn", 0) or 0)
        resume_max_turns = used_turns + max_turns
        try:
            result = await Runner.run(
                agent,
                state,
                max_turns=resume_max_turns,
                run_config=RunConfig(tracing_disabled=True),
            )
        except ModelBehaviorError as exc:
            logger.warning("agents-sdk resumed run behavior error: %s", exc)
            return LoopResult(
                reply="恢复执行时模型调用了当前模式下不可用的工具，已停止。请切换 Build 模式重新发起。",
                steps=tracked_steps,
                used_tools=tracked,
                total_steps=len(tracked) or 1,
            )
        except MaxTurnsExceeded:
            logger.warning("agents-sdk resumed run exceeded turn budget")
            return LoopResult(
                reply="已用完工具轮次上限，无法继续执行。请重新发起请求或降低任务复杂度。",
                steps=tracked_steps,
                used_tools=tracked,
                total_steps=len(tracked) or 1,
            )
        interruptions = getattr(result, "interruptions", None) or []
        if interruptions:
            next_pending, step = _pending_from_interruption(
                interruptions[0],
                tools_by_name=tools_by_name,
                working_dir=working_dir,
                require_confirm=require_confirm,
                sdk_state=result.to_state().to_string(),
            )
            return LoopResult(
                reply=f"我需要你的确认才能继续：\n\n{next_pending.description}\n\n是否允许？",
                steps=[step],
                used_tools=tracked,
                total_steps=len(tracked) or 1,
                pending_confirmation=next_pending,
                pending_step=step,
                messages_snapshot=_safe_messages(messages),
            )
        return _result_to_loop_result(
            result,
            safe_messages=_safe_messages(messages),
            tracked_steps=tracked_steps,
        )

    return asyncio.run(_resume())


def _result_to_loop_result(
    result: Any,
    *,
    safe_messages: list[dict[str, str]],
    tracked_steps: list[StepResult] | None = None,
) -> LoopResult:
    reply = getattr(result, "final_output", None)
    final_reply = reply if isinstance(reply, str) else ("" if reply is None else str(reply))
    used_tools: list[str] = []
    for step in getattr(result, "steps", []) or []:
        data = getattr(step, "data", {}) or {}
        name = data.get("tool_name") or getattr(step, "name", None)
        if isinstance(name, str) and name and name not in used_tools:
            used_tools.append(name)
    steps = list(tracked_steps) if tracked_steps else []
    user_message = resolve_turn_user_message(safe_messages) if safe_messages else ""
    final_reply, verified, note = enforce_grounded_reply(
        final_reply,
        user_message,
        used_tools,
        grounding_verified=True,
        grounding_note="",
    )
    return LoopResult(
        reply=final_reply,
        steps=steps,
        used_tools=used_tools,
        total_steps=len(used_tools) or 1,
        grounding_verified=verified,
        grounding_note=note,
    )
