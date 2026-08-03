"""aisuite Runner adapter preserving Lumina LoopResult / confirm contracts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from aisuite import Agent, RequireApprovalPolicy, Runner, ToolPolicyContext, ToolPolicyDecision

from secretary.agent.aisuite_bridge import build_aisuite_client, to_aisuite_model
from secretary.agent.artifact_paths import collect_artifact_paths
from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.grounding import enforce_grounded_reply, resolve_turn_user_message
from secretary.agent.harness_config import ConfirmRequireConfig
from secretary.agent.llm_config import LlmConfig, model_supports_thinking
from secretary.agent.loop import LoopResult, PendingConfirmation, StepResult
from secretary.agent.progress_events import ProgressEvent
from secretary.agent.tools.base import Tool, _coerce_to_tool_result
from secretary.services.file_auth import FileAuthService

logger = logging.getLogger(__name__)


class SubagentPausedError(Exception):
    """Raised when spawn_subagent pauses for nested confirmation."""

    def __init__(self, state: Any) -> None:
        self.state = state
        super().__init__("subagent paused")


def pause_approval_policy(
    needs_confirm: Callable[[str, dict[str, Any]], bool],
) -> RequireApprovalPolicy:
    """Build a policy that pauses (does not hard-deny) when Lumina needs confirm."""

    def _callback(context: ToolPolicyContext) -> ToolPolicyDecision:
        if needs_confirm(context.tool_name, dict(context.arguments or {})):
            return ToolPolicyDecision(
                allowed=False,
                reason="needs_human_approval",
                metadata={"pause_for_approval": True},
            )
        return ToolPolicyDecision(allowed=True)

    return RequireApprovalPolicy(_callback)


def split_system_and_input(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Split Lumina chat messages into Agent.instructions + Runner input."""
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


def wrap_lumina_tools(
    tools: list[Tool],
    working_dir: Path,
    *,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    used_tools: list[str] | None = None,
    on_subagent_paused: Callable[[Any], None] | None = None,
) -> list[Callable[..., Any]]:
    """Convert Lumina Tool objects into plain callables for aisuite Agent.tools."""
    import inspect

    callables: list[Callable[..., Any]] = []
    tracked = used_tools if used_tools is not None else []
    for tool in tools:
        schema = tool.schema() if hasattr(tool, "schema") else {}
        name = str(schema.get("name") or getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        description = str(schema.get("description") or "")
        parameters = schema.get("parameters") if isinstance(schema.get("parameters"), dict) else {}

        def _make(
            t: Tool,
            tool_name: str,
            tool_description: str,
            tool_parameters: dict[str, Any],
        ) -> Callable[..., Any]:
            props = tool_parameters.get("properties")
            prop_names = list(props.keys()) if isinstance(props, dict) else []
            required = set(tool_parameters.get("required") or [])

            def _fn(**kwargs: Any) -> str:
                if cancel_check is not None and cancel_check():
                    raise RuntimeError("cancelled")
                if hasattr(t, "bind_progress"):
                    t.bind_progress(progress_callback)
                if hasattr(t, "bind_cancel_check"):
                    t.bind_cancel_check(cancel_check)
                if progress_callback is not None:
                    progress_callback(
                        ProgressEvent(
                            kind="tool_started",
                            iteration=len(tracked) + 1,
                            tool_name=tool_name,
                        )
                    )
                try:
                    raw = t.execute(dict(kwargs), working_dir)
                    text = _coerce_to_tool_result(raw, tool_name=tool_name).to_output_string()
                except Exception as exc:
                    text = f"Error executing {tool_name}: {exc}"
                    logger.warning("aisuite tool %s failed: %s", tool_name, exc)
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
                                    dict(kwargs),
                                    working_dir,
                                    output=text,
                                    success=ok,
                                )
                            ),
                        )
                    )
                if tool_name == "spawn_subagent" and hasattr(t, "consume_paused"):
                    paused = t.consume_paused()
                    if paused is not None:
                        if on_subagent_paused is not None:
                            on_subagent_paused(paused)
                        raise SubagentPausedError(paused)
                return text

            _fn.__name__ = tool_name
            _fn.__doc__ = tool_description or tool_name
            sig_params: list[inspect.Parameter] = []
            annotations: dict[str, Any] = {"return": str}
            for key in prop_names:
                annotations[key] = Any
                if key in required:
                    sig_params.append(
                        inspect.Parameter(
                            key,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            annotation=Any,
                        )
                    )
                else:
                    sig_params.append(
                        inspect.Parameter(
                            key,
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            default=None,
                            annotation=Any,
                        )
                    )
            if not sig_params:
                def _empty_fn() -> str:
                    return _fn()

                _empty_fn.__name__ = tool_name
                _empty_fn.__doc__ = tool_description or tool_name
                _empty_fn.__signature__ = inspect.Signature()  # type: ignore[attr-defined]
                _empty_fn.__annotations__ = {"return": str}
                return _empty_fn
            _fn.__signature__ = inspect.Signature(sig_params)  # type: ignore[attr-defined]
            _fn.__annotations__ = annotations
            return _fn

        params = dict(parameters) if isinstance(parameters, dict) else {}
        callables.append(_make(tool, name, description, params))
    return callables


def _thinking_model_settings(
    llm_config: LlmConfig,
    *,
    thinking: str,
    reasoning_effort: str | None,
    temperature: float,
) -> dict[str, Any]:
    """Build aisuite Agent.model_settings; DeepSeek thinking goes in extra_body."""
    settings: dict[str, Any] = {"temperature": temperature}
    if not model_supports_thinking(llm_config.model):
        return settings
    extra_body: dict[str, Any] = {}
    if thinking == "disabled":
        extra_body["thinking"] = {"type": "disabled"}
    else:
        extra_body["thinking"] = {"type": "enabled"}
        if reasoning_effort in {"low", "high", "max"}:
            extra_body["reasoning_effort"] = reasoning_effort
    if extra_body:
        settings["extra_body"] = extra_body
    return settings


def _used_tools_from_result(result: Any, tracked: list[str]) -> list[str]:
    if tracked:
        return list(tracked)
    names: list[str] = []
    for step in getattr(result, "steps", []) or []:
        data = getattr(step, "data", {}) or {}
        name = data.get("tool_name") or getattr(step, "name", None)
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return names


def run_result_to_loop_result(
    result: Any,
    *,
    tools_by_name: dict[str, Tool],
    working_dir: Path,
    used_tools: list[str] | None = None,
) -> LoopResult:
    """Map an aisuite RunResult onto Lumina LoopResult."""
    status = getattr(result, "status", "completed")
    messages = list(getattr(result, "messages", []) or [])
    tools_used = _used_tools_from_result(result, used_tools or [])
    total_steps = max(len(getattr(result, "steps", []) or []), len(tools_used))

    if status == "requires_input":
        pending_raw = (getattr(result, "metadata", None) or {}).get("pending_approval") or {}
        tool_name = str(pending_raw.get("name") or "")
        arguments = dict(pending_raw.get("arguments") or {})
        tool = tools_by_name.get(tool_name)
        if tool is not None:
            description = tool.describe_action(arguments, working_dir)
            risk = tool.risk_level
            _, kind = tool_requires_confirmation(
                tool,
                arguments,
                working_dir=working_dir,
                file_auth=None,
                require_confirm=None,
            )
        else:
            description = str(pending_raw.get("reason") or "needs confirmation")
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
        )
        step = StepResult(
            thought="",
            tool_call=None,
            tool_output=f"[Waiting for user confirmation] {description}",
            needs_confirmation=True,
        )
        return LoopResult(
            reply=f"我需要你的确认才能继续：\n\n{description}\n\n是否允许？",
            steps=[step],
            used_tools=tools_used,
            total_steps=total_steps or 1,
            pending_confirmation=pending,
            pending_step=step,
            messages_snapshot=messages,
        )

    output = getattr(result, "final_output", None)
    reply = output if isinstance(output, str) else ("" if output is None else str(output))
    return LoopResult(
        reply=reply,
        steps=[],
        used_tools=tools_used,
        total_steps=total_steps,
        messages_snapshot=messages,
    )


def run_with_aisuite(
    *,
    llm_config: LlmConfig,
    messages: list[dict[str, Any]],
    tools: list[Tool],
    working_dir: Path,
    max_turns: int,
    temperature: float = 0.7,
    thinking: str = "enabled",
    reasoning_effort: str | None = "high",
    file_auth: FileAuthService | None = None,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_subagent_paused: Callable[[Any], None] | None = None,
    explicit_working_dir: bool = False,
    require_confirm: ConfirmRequireConfig | None = None,
) -> LoopResult:
    """Run one aisuite Agent turn and map to LoopResult (confirm + grounding)."""
    tools_by_name = {t.name: t for t in tools if getattr(t, "name", "")}
    tracked: list[str] = []
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
                logger.warning("aisuite workspace preflight list_dir failed: %s", exc)

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

    instructions, input_messages = split_system_and_input(run_messages)
    client = build_aisuite_client(llm_config)
    agent = Agent(
        name="lumina",
        model=to_aisuite_model(llm_config),
        instructions=instructions or None,
        tools=wrap_lumina_tools(
            tools,
            working_dir,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            used_tools=tracked,
            on_subagent_paused=on_subagent_paused,
        ),
        model_settings=_thinking_model_settings(
            llm_config,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
        ),
    )
    try:
        result = Runner.run_sync(
            agent,
            input_messages if input_messages else run_messages,
            client=client,
            max_turns=max_turns,
            tool_policy=pause_approval_policy(_needs_confirm),
        )
    except SubagentPausedError:
        return LoopResult(
            reply="子任务等待确认…",
            steps=[],
            used_tools=tracked,
            total_steps=len(tracked) or 1,
            messages_snapshot=list(run_messages),
        )

    loop_result = run_result_to_loop_result(
        result,
        tools_by_name=tools_by_name,
        working_dir=working_dir,
        used_tools=tracked,
    )
    if loop_result.pending_confirmation is not None:
        return loop_result

    safe_messages: list[dict[str, str]] = []
    for message in run_messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        safe_messages.append(
            {"role": role, "content": content if isinstance(content, str) else ""}
        )
    user_message = resolve_turn_user_message(safe_messages)
    reply, verified, note = enforce_grounded_reply(
        loop_result.reply,
        user_message,
        loop_result.used_tools,
        grounding_verified=True,
        grounding_note="",
    )
    return LoopResult(
        reply=reply,
        steps=loop_result.steps,
        used_tools=loop_result.used_tools,
        total_steps=loop_result.total_steps,
        messages_snapshot=loop_result.messages_snapshot,
        grounding_verified=verified,
        grounding_note=note,
    )


def resume_with_aisuite(
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
    file_auth: FileAuthService | None = None,
    progress_callback: Callable[[ProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_subagent_paused: Callable[[Any], None] | None = None,
) -> LoopResult:
    """Execute a confirmed tool, append the result, continue via aisuite Runner."""
    tools_by_name = {t.name: t for t in tools if getattr(t, "name", "")}
    tool = tools_by_name.get(pending.tool_name)
    continued = list(messages)
    if tool is None:
        return LoopResult(
            reply="Error: tool no longer available",
            steps=[],
            used_tools=[],
            total_steps=0,
        )
    try:
        raw = tool.execute(pending.arguments, working_dir)
        tool_output = _coerce_to_tool_result(raw, tool_name=pending.tool_name).to_output_string()
    except Exception as exc:
        tool_output = f"Error executing {pending.tool_name}: {exc}"

    tool_call_id = ""
    for message in reversed(continued):
        if message.get("role") != "assistant":
            continue
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                fn_raw = call.get("function")
                fn = fn_raw if isinstance(fn_raw, dict) else {}
                if str(fn.get("name") or "") == pending.tool_name:
                    tool_call_id = str(call.get("id") or "")
                    break
        if tool_call_id:
            break
    if tool_call_id:
        continued.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": tool_output,
            }
        )
    else:
        continued.append(
            {
                "role": "user",
                "content": (
                    f"[User confirmed: {pending.description}]\n"
                    f"[Tool Result: {pending.tool_name}]\n{tool_output}"
                ),
            }
        )

    result = run_with_aisuite(
        llm_config=llm_config,
        messages=continued,
        tools=tools,
        working_dir=working_dir,
        max_turns=max_turns,
        temperature=temperature,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        file_auth=file_auth,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        on_subagent_paused=on_subagent_paused,
    )
    if pending.tool_name not in result.used_tools:
        result.used_tools.insert(0, pending.tool_name)
    return result
