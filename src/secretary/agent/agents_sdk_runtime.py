"""OpenAI Agents SDK backend preserving Lumina LoopResult / confirm contracts.

Replaces the aisuite Runner as the primary harness backend. The Agents SDK
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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from agents import (
    Agent,
    ModelSettings,
    Runner,
    RunState,
    set_default_openai_api,
    set_default_openai_client,
)
from agents.run import RunConfig
from agents.tool import FunctionTool
from openai import AsyncOpenAI

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
    return AsyncOpenAI(api_key=llm_config.api_key, base_url=base or None)


def _bind_default_client(llm_config: LlmConfig) -> None:
    """Point the SDK's shared OpenAI provider at Lumina's LLM config.

    Global but single-user: every turn overwrites with the same config.
    """
    set_default_openai_client(_build_async_client(llm_config), use_for_tracing=False)
    set_default_openai_api("chat_completions")


def _model_settings(
    llm_config: LlmConfig,
    *,
    thinking: str,
    reasoning_effort: str | None,
    temperature: float,
    strict_tools: bool = False,
) -> ModelSettings:
    """ModelSettings; DeepSeek thinking goes through extra_body."""
    settings: dict[str, Any] = {"temperature": temperature}
    if model_supports_thinking(llm_config.model):
        extra_body: dict[str, Any] = {}
        if thinking == "disabled":
            extra_body["thinking"] = {"type": "disabled"}
        else:
            extra_body["thinking"] = {"type": "enabled"}
            if reasoning_effort in {"low", "high", "max"}:
                extra_body["reasoning_effort"] = reasoning_effort
        if extra_body:
            settings["extra_body"] = extra_body
    return ModelSettings(**settings)


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
) -> Agent:
    return Agent(
        name="lumina",
        model=llm_config.model,
        instructions=instructions or None,
        tools=cast(Any, tools),
        model_settings=model_settings,
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
) -> LoopResult:
    """Run one Agents SDK turn and map to LoopResult (HITL + grounding)."""
    _bind_default_client(llm_config)
    tools_by_name = {t.name: t for t in tools if getattr(t, "name", "")}
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
    agent = _build_agent(
        llm_config,
        instructions=instructions,
        tools=wrap_lumina_tools(
            tools,
            working_dir,
            needs_confirm=_needs_confirm,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            tracked=tracked,
            steps_out=tracked_steps,
            strict_tools=strict_tools,
        ),
        model_settings=_model_settings(
            llm_config,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            strict_tools=strict_tools,
        ),
    )
    # Retry ladder mirroring the legacy AgentLoop (shared budget): the model
    # often *claims* it searched / verified without calling a tool; give it a
    # chance to ground the answer instead of ending the turn unverified.
    max_shared_retries = 3
    shared_retries = 0
    final_reply = ""
    verified = True
    note = ""
    while True:
        current_input = _split_system_and_input(run_messages)[1]
        result = Runner.run_sync(
            agent,
            cast(Any, current_input if current_input else run_messages),
            max_turns=max_turns,
            run_config=RunConfig(tracing_disabled=True),
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

        reply = getattr(result, "final_output", None)
        final_reply = reply if isinstance(reply, str) else ("" if reply is None else str(reply))
        safe_messages = _safe_messages(run_messages)
        user_message = resolve_turn_user_message(safe_messages)

        if shared_retries >= max_shared_retries:
            break

        retry_kind = _pick_retry(
            final_reply,
            tracked,
            user_message,
            tracked_steps,
        )
        if retry_kind is None:
            break
        shared_retries += 1
        if retry_kind == "web_claim":
            # Legacy behavior: inject an actual web_search execution.
            web_tool = tools_by_name.get("web_search")
            if web_tool is None:
                break
            try:
                output = _coerce_to_tool_result(
                    web_tool.execute({"query": user_message.strip()[:200]}, working_dir),
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
) -> LoopResult:
    """Approve a paused SDK interruption (RunState round-trip) and continue.

    ``messages`` is the pause-time conversation snapshot used to rebuild the
    agent (instructions + tools) for ``RunState.from_string``, which requires
    the original top-level agent definition.
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

    async def _resume() -> LoopResult:
        instructions, input_messages = _split_system_and_input(messages)
        agent = _build_agent(
            llm_config,
            instructions=instructions,
            tools=wrap_lumina_tools(
                tools,
                working_dir,
                needs_confirm=_needs_confirm,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
                tracked=tracked,
                steps_out=tracked_steps,
                strict_tools=strict_tools,
            ),
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
        if not approved:
            raise ValueError(f"paused interruption {pending.tool_name} not found in state")
        result = await Runner.run(
            agent, state, max_turns=max_turns, run_config=RunConfig(tracing_disabled=True)
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
