"""Rule-based sub-agent archetype selection (PRD F24)."""

from __future__ import annotations

from secretary.agent.subagent.policy import BUILTIN_ARCHETYPES

_VERIFY_MARKERS = (
    "验证",
    "审查",
    "审核",
    "检查是否",
    "verify",
    "review",
    "audit",
    "确认是否通过",
)

_WORKER_MARKERS = (
    "修改",
    "写入",
    "实现",
    "修复",
    "创建文件",
    "改代码",
    "写代码",
    "refactor",
    "implement",
    "fix",
    "patch",
    "apply",
    "编辑",
    "删除文件",
)

_PLAN_MARKERS = (
    "规划",
    "方案",
    "计划",
    "拆解",
    "roadmap",
    "怎么实现",
    "如何实现",
    "架构设计",
    "里程碑",
)


def select_archetype(
    goal: str,
    *,
    explicit: str | None = None,
    success_criteria: str = "",
    custom_names: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Pick explore/worker/verify/plan (or custom name).

    Priority:
    1. Explicit valid archetype
    2. Custom name exact match in goal
    3. verify clues (success_criteria or markers)
    4. plan markers (before worker, so "规划实现" stays plan)
    5. worker markers
    6. explore default
    """
    custom = {name.strip().lower() for name in (custom_names or []) if name.strip()}
    raw_explicit = (explicit or "").strip().lower()
    if raw_explicit:
        if raw_explicit in BUILTIN_ARCHETYPES or raw_explicit in custom:
            return raw_explicit
        # Invalid explicit falls through to inference.

    goal_text = (goal or "").strip()
    lowered = goal_text.lower()

    for name in custom:
        if name and name in lowered:
            return name

    if success_criteria.strip() or _contains_any(lowered, _VERIFY_MARKERS):
        return "verify"
    # Prefer plan when both plan and worker markers appear (e.g. "规划实现步骤").
    if _contains_any(lowered, _PLAN_MARKERS):
        return "plan"
    if _contains_any(lowered, _WORKER_MARKERS):
        return "worker"
    return "explore"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in text for marker in markers)
