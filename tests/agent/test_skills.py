"""Tests for skill manager."""

from pathlib import Path

import pytest

from secretary.agent import skills as skills_module
from secretary.agent.skills import SkillManager, parse_skill_markdown
from secretary.exceptions import AgentError


def test_parse_skill_frontmatter() -> None:
    text = """---
name: demo-skill
description: A demo skill for testing.
---

# Body
"""
    meta = parse_skill_markdown(text)
    assert meta["name"] == "demo-skill"
    assert "demo skill" in meta["description"]


def test_discover_nested_skill_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_root = tmp_path / ".hermes"
    nested = agent_root / "hermes-agent" / "optional-skills" / "research" / "demo-skill"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: nested-skill\ndescription: nested path\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_module, "AGENT_SCAN_ROOTS", (agent_root,))

    manager = SkillManager(tmp_path / "data")
    records = manager.catalog()
    assert any(item.name == "nested-skill" for item in records)


def test_install_skill_from_allowed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_root = tmp_path / ".hermes"
    source = agent_root / "skills" / "demo-skill"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: copied skill\n---\n# Demo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_module, "AGENT_SCAN_ROOTS", (agent_root,))

    manager = SkillManager(tmp_path / "data")
    record = manager.install(str(source))
    assert record.installed is True
    assert (manager.skills_dir / "demo-skill" / "SKILL.md").exists()


def test_install_all_skips_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_root = tmp_path / ".agents"
    for name in ("alpha", "beta"):
        folder = agent_root / "pack" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name}\n---\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(skills_module, "AGENT_SCAN_ROOTS", (agent_root,))

    manager = SkillManager(tmp_path / "data")
    result = manager.install_all()
    assert result.installed == 2
    assert result.skipped == 0

    repeat = manager.install_all()
    assert repeat.installed == 0
    assert repeat.skipped == 2


def test_install_rejects_unknown_source(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "evil"
    outside.mkdir(parents=True)
    (outside / "SKILL.md").write_text("---\nname: evil\n---\n", encoding="utf-8")
    manager = SkillManager(tmp_path / "data")
    with pytest.raises(AgentError, match="扫描到"):
        manager.install(str(outside))
