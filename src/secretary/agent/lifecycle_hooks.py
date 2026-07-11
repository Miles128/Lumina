"""生命周期钩子：在 AgentLoop 关键节点注入可观察、可修改的逻辑。

三个钩子点：
- BeforeTurn：每轮迭代开始前，可审计/限流/短路
- BeforeModelCall：调用 LLM 前，可修改 payload 或注入上下文
- BeforeToolExecution：执行工具前，可修改参数或阻止执行

钩子是可选的，不传则不影响任何行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from secretary.agent.stop_hooks import LoopSnapshot


@dataclass(frozen=True)
class TurnContext:
    """每轮迭代的上下文快照。"""
    snapshot: LoopSnapshot
    messages: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ModelCallContext:
    """LLM 调用前的上下文快照。"""
    snapshot: LoopSnapshot
    messages: tuple[dict[str, Any], ...] = ()
    tool_schemas: tuple[dict[str, Any], ...] = ()
    temperature: float = 0.7


@dataclass(frozen=True)
class ToolExecContext:
    """工具执行前的上下文快照。"""
    snapshot: LoopSnapshot
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    working_dir: Path | None = None


@dataclass(frozen=True)
class HookDecision:
    """钩子返回的决策。"""
    should_skip: bool = False
    reason: str = ""
    modified_arguments: dict[str, Any] | None = None


class BeforeTurnHook(Protocol):
    """每轮迭代开始前调用。should_skip=True 可短路该轮。"""
    def before_turn(self, ctx: TurnContext) -> HookDecision: ...


class BeforeModelCallHook(Protocol):
    """调用 LLM 前调用。用于审计、限流、注入上下文。"""
    def before_model_call(self, ctx: ModelCallContext) -> HookDecision: ...


class BeforeToolExecutionHook(Protocol):
    """执行工具前调用。modified_arguments 可覆盖工具参数，should_skip 可阻止执行。"""
    def before_tool_execution(self, ctx: ToolExecContext) -> HookDecision: ...
