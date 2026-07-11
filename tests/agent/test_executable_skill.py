"""Tests for executable skill sandbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.agent.executable_skill import (
    ExecutableSkill,
    ExecutableSkillManager,
    SkillExecutionResult,
)
from secretary.exceptions import AgentError


def _create_skill(tmp_path: Path, name: str, run_code: str, *, timeout: int = 30) -> Path:
    manager = ExecutableSkillManager(tmp_path)
    return manager.create_executable_skill(
        name=name,
        description=f"Skill {name}",
        run_code=run_code,
        parameters=["query"],
        timeout=timeout,
    )


def test_skill_executes_and_prints_args(tmp_path: Path) -> None:
    skill_dir = _create_skill(
        tmp_path,
        "echo",
        'print("got", args.get("query"))',
    )
    skill = ExecutableSkill(skill_dir)
    result = skill.execute({"query": "hello"})

    assert isinstance(result, SkillExecutionResult)
    assert result.success is True
    assert result.exit_code == 0
    assert "got hello" in result.output


def test_skill_can_write_to_sandbox_dir(tmp_path: Path) -> None:
    skill_dir = _create_skill(
        tmp_path,
        "writer",
        'open("out.txt", "w").write(args.get("query")); print("ok")',
    )
    skill = ExecutableSkill(skill_dir)
    result = skill.execute({"query": "data"})

    assert result.success is True
    assert "ok" in result.output


def test_skill_can_write_to_skill_dir(tmp_path: Path) -> None:
    marker_path = tmp_path / "skills" / "self_writer" / "marker.txt"
    skill_dir = _create_skill(
        tmp_path,
        "self_writer",
        f'import pathlib; pathlib.Path(r"{marker_path}").write_text("x"); print("ok")',
    )
    skill = ExecutableSkill(skill_dir)
    result = skill.execute({"query": ""})

    assert result.success is True
    assert marker_path.read_text() == "x"


def test_skill_cannot_write_outside_allowed_dirs(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "evil.txt"

    skill_dir = _create_skill(
        tmp_path,
        "escape",
        f'open(r"{target}", "w").write("pwned")',
    )
    skill = ExecutableSkill(skill_dir)
    result = skill.execute({"query": ""})

    assert result.success is False
    assert "Sandbox blocked" in (result.error or "")
    assert not target.exists()


def test_skill_cannot_import_dangerous_module(tmp_path: Path) -> None:
    skill_dir = _create_skill(
        tmp_path,
        "importer",
        "import subprocess; print('bad')",
    )
    skill = ExecutableSkill(skill_dir)
    result = skill.execute({"query": ""})

    assert result.success is False
    assert "not allowed" in (result.error or "")


def test_skill_timeout_is_enforced(tmp_path: Path) -> None:
    skill_dir = _create_skill(
        tmp_path,
        "slow",
        "import time; time.sleep(10); print('done')",
        timeout=1,
    )
    skill = ExecutableSkill(skill_dir)
    result = skill.execute({"query": ""})

    assert result.success is False
    assert "Timeout" in (result.error or "")


def test_manager_runs_skill_by_name(tmp_path: Path) -> None:
    _create_skill(tmp_path, "greeter", 'print("hi", args.get("query"))')
    manager = ExecutableSkillManager(tmp_path)
    result = manager.execute_skill("greeter", {"query": "world"})

    assert result.success is True
    assert "hi world" in result.output


def test_prompt_only_skill_raises_on_execute(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_dir = skills_dir / "prompt_only"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Prompt skill\n", encoding="utf-8")

    manager = ExecutableSkillManager(tmp_path)
    with pytest.raises(AgentError, match="prompt-only"):
        manager.execute_skill("prompt_only", {})
