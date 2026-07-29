"""FR-53 WriteGate: proposals jail vs landing roles."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.agent.write_gate import (
    WriteGateError,
    assert_write_allowed,
    display_name_for_role,
    is_proposals_path,
    proposals_root,
    write_gate_scope,
)


def test_display_names_are_chinese_job_titles() -> None:
    assert display_name_for_role("root") == "项目主管"
    assert display_name_for_role("pro") == "方案主张"
    assert display_name_for_role("write_gate") == "项目落地"


def test_proposals_root_prefers_workspace(tmp_path: Path) -> None:
    root = proposals_root(run_id="run-1", workspace=tmp_path)
    assert root == (tmp_path / ".lumina" / "proposals" / "run-1").resolve()


def test_worker_may_write_proposals_only(tmp_path: Path) -> None:
    run_id = "r1"
    draft = proposals_root(run_id=run_id, workspace=tmp_path) / "a.py"
    business = tmp_path / "src" / "a.py"
    with write_gate_scope(role="worker", run_id=run_id, workspace=tmp_path):
        assert_write_allowed(draft)
        with pytest.raises(WriteGateError, match="只能写入草稿目录"):
            assert_write_allowed(business)


def test_pro_con_jailed(tmp_path: Path) -> None:
    run_id = "debate"
    draft = proposals_root(run_id=run_id, workspace=tmp_path) / "patch.diff"
    with write_gate_scope(role="pro", run_id=run_id, workspace=tmp_path):
        assert_write_allowed(draft)
    with write_gate_scope(role="con", run_id=run_id, workspace=tmp_path):
        with pytest.raises(WriteGateError):
            assert_write_allowed(tmp_path / "README.md")


def test_referee_locked_blocks_business_allows_proposals(tmp_path: Path) -> None:
    run_id = "r2"
    draft = proposals_root(run_id=run_id, workspace=tmp_path) / "x.md"
    business = tmp_path / "app.py"
    with write_gate_scope(
        role="referee", run_id=run_id, workspace=tmp_path, unlocked=False
    ):
        assert_write_allowed(draft)
        with pytest.raises(WriteGateError, match="闸门已锁定"):
            assert_write_allowed(business)


def test_referee_unlocked_may_write_business(tmp_path: Path) -> None:
    business = tmp_path / "app.py"
    with write_gate_scope(
        role="referee", run_id="r3", workspace=tmp_path, unlocked=True
    ):
        assert_write_allowed(business)


def test_root_without_run_id_remains_open(tmp_path: Path) -> None:
    """Primary agent legacy path: no jail until spawn context binds run_id."""
    assert_write_allowed(tmp_path / "any.py")


def test_is_proposals_path(tmp_path: Path) -> None:
    run_id = "z"
    inside = proposals_root(run_id=run_id, workspace=tmp_path) / "f.txt"
    assert is_proposals_path(inside, run_id=run_id, workspace=tmp_path)
    assert not is_proposals_path(tmp_path / "f.txt", run_id=run_id, workspace=tmp_path)


def test_write_tool_respects_gate(tmp_path: Path) -> None:
    from secretary.agent.tools.fs import WriteTool

    tool = WriteTool()
    business = tmp_path / "secret.py"
    draft_dir = proposals_root(run_id="tool-run", workspace=tmp_path)
    draft = draft_dir / "secret.py"
    with write_gate_scope(role="worker", run_id="tool-run", workspace=tmp_path):
        denied = tool.execute(
            {"path": str(business), "content": "x=1\n"},
            tmp_path,
        )
        assert "WriteGate" in str(denied)
        ok = tool.execute(
            {"path": str(draft), "content": "x=1\n"},
            tmp_path,
        )
        assert str(ok).startswith("OK:")
        assert draft.read_text(encoding="utf-8") == "x=1\n"
