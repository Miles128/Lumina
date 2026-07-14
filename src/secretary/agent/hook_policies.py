"""Configurable permission / policy hooks for AgentLoop."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from secretary.agent.agent_profile import AgentProfile
from secretary.agent.lifecycle_hooks import (
    AfterToolContext,
    AfterToolDecision,
    AfterToolExecutionHook,
    BeforeToolExecutionHook,
    HookDecision,
    ToolExecContext,
)
from secretary.agent.permission_guard import PLAN_DENY_TOOL_NAMES, tool_allowed_for_profile
from secretary.agent.tools.base import Tool

logger = logging.getLogger(__name__)

DEFAULT_COMMAND_DENY = ("rm -rf /", "sudo ")
DEFAULT_MAX_TOOL_OUTPUT_CHARS = 12_000


@dataclass(frozen=True)
class HooksConfig:
    """Optional hooks block from ~/.lumina/agent.json."""

    path_allowlist: tuple[str, ...] = ()
    command_deny: tuple[str, ...] = DEFAULT_COMMAND_DENY
    max_tool_output_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> HooksConfig:
        if not isinstance(raw, dict):
            return cls()
        allow = raw.get("path_allowlist") or []
        deny = raw.get("command_deny")
        if deny is None:
            deny_tuple: tuple[str, ...] = DEFAULT_COMMAND_DENY
        elif isinstance(deny, list):
            deny_tuple = tuple(str(item) for item in deny)
        else:
            deny_tuple = DEFAULT_COMMAND_DENY
        max_chars = raw.get("max_tool_output_chars", DEFAULT_MAX_TOOL_OUTPUT_CHARS)
        try:
            max_chars_i = int(max_chars)
        except (TypeError, ValueError):
            max_chars_i = DEFAULT_MAX_TOOL_OUTPUT_CHARS
        return cls(
            path_allowlist=tuple(str(item) for item in allow if str(item).strip()),
            command_deny=deny_tuple,
            max_tool_output_chars=max(500, max_chars_i),
        )


@dataclass
class PathAllowlistHook:
    """Deny file tools whose path falls outside the configured allowlist.

    Empty allowlist = no path restriction (default).
    """

    allowlist: tuple[str, ...] = ()
    path_keys: tuple[str, ...] = ("path", "file", "filepath", "target")

    def before_tool_execution(self, ctx: ToolExecContext) -> HookDecision:
        if not self.allowlist:
            return HookDecision()
        path_value = _extract_path_arg(ctx.arguments, self.path_keys)
        if path_value is None:
            return HookDecision()
        resolved = _resolve_tool_path(path_value, ctx.working_dir)
        for prefix in self.allowlist:
            root = Path(prefix).expanduser().resolve()
            try:
                resolved.relative_to(root)
                return HookDecision()
            except ValueError:
                continue
        return HookDecision(
            should_skip=True,
            reason=f"path not in allowlist: {resolved}",
        )


@dataclass
class CommandDenyHook:
    """Block shell/code_exec when the command contains a deny substring."""

    deny_substrings: tuple[str, ...] = DEFAULT_COMMAND_DENY
    command_keys: tuple[str, ...] = ("command", "cmd", "code")

    def before_tool_execution(self, ctx: ToolExecContext) -> HookDecision:
        if not self.deny_substrings:
            return HookDecision()
        if ctx.tool_name not in {"shell", "code_exec"}:
            return HookDecision()
        command = ""
        for key in self.command_keys:
            value = ctx.arguments.get(key)
            if isinstance(value, str) and value.strip():
                command = value
                break
        if not command:
            return HookDecision()
        lowered = command.lower()
        for pattern in self.deny_substrings:
            if pattern and pattern.lower() in lowered:
                return HookDecision(
                    should_skip=True,
                    reason=f"command denied by policy ({pattern!r})",
                )
        return HookDecision()


@dataclass
class PlanPermissionHook:
    """Defense-in-depth: re-check Plan deny list at tool execution time."""

    profile: AgentProfile
    tools_by_name: dict[str, Tool] = field(default_factory=dict)

    def before_tool_execution(self, ctx: ToolExecContext) -> HookDecision:
        if self.profile is not AgentProfile.PLAN:
            return HookDecision()
        name = ctx.tool_name.lower()
        if name in PLAN_DENY_TOOL_NAMES:
            return HookDecision(
                should_skip=True,
                reason=f"plan profile denies tool '{ctx.tool_name}'",
            )
        tool = self.tools_by_name.get(ctx.tool_name)
        if tool is not None and not tool_allowed_for_profile(self.profile, tool):
            return HookDecision(
                should_skip=True,
                reason=f"plan profile denies tool '{ctx.tool_name}'",
            )
        return HookDecision()


@dataclass
class TruncateToolOutputHook:
    """After-tool: truncate oversized tool outputs before they enter history."""

    max_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS

    def after_tool_execution(self, ctx: AfterToolContext) -> AfterToolDecision:
        if len(ctx.tool_output) <= self.max_chars:
            return AfterToolDecision()
        trimmed = ctx.tool_output[: self.max_chars] + "\n…[truncated by AfterTool hook]"
        logger.debug(
            "truncated tool output for %s: %s -> %s chars",
            ctx.tool_name,
            len(ctx.tool_output),
            len(trimmed),
        )
        return AfterToolDecision(modified_output=trimmed)


def build_default_hooks(
    config: HooksConfig,
    *,
    profile: AgentProfile | None = None,
    tools: list[Tool] | None = None,
) -> tuple[list[BeforeToolExecutionHook], list[AfterToolExecutionHook]]:
    """Assemble standard before/after tool hooks from config + profile."""
    before: list[BeforeToolExecutionHook] = [
        PathAllowlistHook(allowlist=config.path_allowlist),
        CommandDenyHook(deny_substrings=config.command_deny),
    ]
    if profile is AgentProfile.PLAN:
        by_name = {tool.name: tool for tool in (tools or [])}
        before.append(PlanPermissionHook(profile=profile, tools_by_name=by_name))
    after: list[AfterToolExecutionHook] = [
        TruncateToolOutputHook(max_chars=config.max_tool_output_chars),
    ]
    return before, after


def _extract_path_arg(arguments: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_tool_path(raw: str, working_dir: Path | None) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        base = working_dir or Path.cwd()
        path = base / path
    try:
        return path.resolve()
    except OSError:
        return path
