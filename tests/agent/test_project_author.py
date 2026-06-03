"""Tests for fast project author lookup."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.identity import is_author_request
from secretary.agent.project_author import (
    infer_project_root,
    is_project_author_question,
    lookup_project_author,
)


def test_is_project_author_question_open_design() -> None:
    assert is_project_author_question("找 open design 的作者")
    assert is_project_author_question("open design 的作者是谁啊")
    assert not is_author_request("找 open design 的作者")
    assert not is_author_request("open design 的作者是谁啊")


def test_lookup_open_design_package_json(tmp_path: Path) -> None:
    projects = tmp_path / "My Projects"
    repo = projects / "open-design"
    repo.mkdir(parents=True)
    (repo / "package.json").write_text(
        '{"name":"open-design","license":"Apache-2.0"}',
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Open Design\n\nApache-2.0.\n", encoding="utf-8")

    root = infer_project_root("找 open design 的作者", projects)
    assert root == repo.resolve()

    reply = lookup_project_author("找 open design 的作者", projects)
    assert reply is not None
    assert "无 `author`" in reply or "无 author" in reply or "无 `author`" in reply.lower() or "author" in reply
    assert "open-design" in reply
    assert "四海" not in reply
