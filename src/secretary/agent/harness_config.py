"""FR-52: tunable harness parameters (defaults + clamp helpers)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TraceRetention = Literal["full", "summary", "off"]
ThinkingMode = Literal["auto", "enabled", "disabled"]
ReasoningEffort = Literal["low", "high", "max"]
RuntimeBackend = Literal["legacy", "agents_sdk"]
WebSearchBackend = Literal["tavily", "responses"]
PermissionMode = Literal["normal", "auto", "yolo", "custom"]

CONFIRM_KIND_KEYS = (
    "write_new",
    "write_modify",
    "write_delete",
    "shell",
    "action",
)


class ConfirmRequireConfig(BaseModel):
    """Which confirmation kinds still pause the agent (True = require confirm)."""

    write_new: bool = True
    write_modify: bool = True
    write_delete: bool = True
    shell: bool = True
    action: bool = True


def apply_permission_mode(mode: PermissionMode) -> ConfirmRequireConfig:
    """Return the require_confirm template for a named permission mode."""
    if mode == "yolo":
        return ConfirmRequireConfig(
            write_new=False,
            write_modify=False,
            write_delete=False,
            shell=False,
            action=False,
        )
    if mode == "auto":
        return ConfirmRequireConfig(
            write_new=False,
            write_modify=True,
            write_delete=True,
            shell=True,
            action=False,
        )
    # normal / custom fallback → safe defaults
    return ConfirmRequireConfig()


def infer_permission_mode(require_confirm: ConfirmRequireConfig) -> PermissionMode:
    """Map a require_confirm table back to a named mode, or custom."""
    presets: tuple[PermissionMode, ...] = ("normal", "auto", "yolo")
    dump = require_confirm.model_dump()
    for mode in presets:
        if dump == apply_permission_mode(mode).model_dump():
            return mode
    return "custom"


class HarnessConfig(BaseModel):
    """Runtime knobs for the self-hosted agent harness.

    Hard limits such as ``MAX_SPAWN_DEPTH=1`` are never exposed here.
    """

    max_tool_rounds: int = Field(default=20, ge=1, le=64)
    light_max_steps: int = Field(default=3, ge=1, le=16)
    compaction_max_tokens: int = Field(default=24_000, ge=4_000, le=128_000)
    compaction_keep_tail: int = Field(default=8, ge=2, le=64)
    trace_retention: TraceRetention = "full"
    trace_retain_days: int = Field(default=30, ge=0, le=365)
    max_tool_output_chars: int = Field(default=12_000, ge=500, le=100_000)
    # DeepSeek V4 thinking controls (ignored for non-DeepSeek models).
    thinking_mode: ThinkingMode = "auto"
    reasoning_effort: ReasoningEffort = "high"
    strict_tools: bool = False
    # Backend selection: ``agents_sdk`` (default) drives turns through the
    # OpenAI Agents SDK Runner (native HITL + RunState persistence); ``legacy``
    # uses the in-house AgentLoop. All backends fall back to AgentLoop when
    # spawn_subagent / force_web_first are in play (nested pause stack not
    # ported yet).
    runtime_backend: RuntimeBackend = "agents_sdk"
    # tavily = Lumina's own web_search tool (Tavily/Bocha API);
    # responses = DeepSeek server-side web_search via the Responses API.
    web_search_backend: WebSearchBackend = "tavily"
    # Confirmation policy (FR-46 editable): presets + fine-grained kinds.
    permission_mode: PermissionMode = "normal"
    require_confirm: ConfirmRequireConfig = Field(default_factory=ConfirmRequireConfig)


def resolve_max_steps(harness: HarnessConfig, *, light_mode: bool) -> int:
    if light_mode:
        return harness.light_max_steps
    return harness.max_tool_rounds


def resolve_agent_thinking(
    harness: HarnessConfig,
    *,
    light_mode: bool = False,
) -> tuple[str, str | None]:
    """Return (thinking, reasoning_effort) for AgentLoop / tool-calling turns.

    ``auto`` → thinking enabled with configured effort (light → low).
    """
    if harness.thinking_mode == "disabled":
        return "disabled", None
    effort: str = harness.reasoning_effort
    if light_mode and effort == "max":
        effort = "high"
    elif light_mode and effort == "high":
        effort = "low"
    if harness.thinking_mode == "enabled":
        return "enabled", effort
    # auto
    return "enabled", effort


def resolve_direct_thinking(harness: HarnessConfig) -> tuple[str, str | None]:
    """DIRECT / utility completions: prefer non-thinking unless forced on."""
    if harness.thinking_mode == "enabled":
        return "enabled", harness.reasoning_effort
    return "disabled", None
