"""Unit tests for subagent archetype router."""

from __future__ import annotations

from secretary.agent.subagent.archetype_router import select_archetype


def test_select_archetype_explicit_wins() -> None:
    assert select_archetype("规划一下", explicit="worker") == "worker"


def test_select_archetype_verify_from_criteria() -> None:
    assert select_archetype("check it", success_criteria="pytest passes") == "verify"


def test_select_archetype_worker_markers() -> None:
    assert select_archetype("请修改并实现这个功能") == "worker"


def test_select_archetype_plan_markers() -> None:
    assert select_archetype("请规划实现方案") == "plan"


def test_select_archetype_default_explore() -> None:
    assert select_archetype("这个目录里有什么") == "explore"
