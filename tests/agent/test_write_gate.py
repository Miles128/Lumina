"""FR-53 WriteGate: proposals jail vs landing roles."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.agent.write_gate import (
    DEFAULT_JAILED_ROLE,
    DEFAULT_RUN_ID,
    DISPLAY_NAMES,
    JAILED_ROLES,
    LANDING_ROLES,
    PROPOSALS_REL_PARTS,
    WriteGateError,
    assert_write_allowed,
    display_name_for_role,
    get_write_gate,
    is_landing_role,
    is_proposals_path,
    normalize_run_id,
    proposals_root,
    role_for_archetype,
    subagent_write_gate_scope,
    write_gate_scope,
)


def test_display_names_cover_all_known_roles() -> None:
    for role in LANDING_ROLES | JAILED_ROLES:
        assert role in DISPLAY_NAMES
        assert display_name_for_role(role)
    assert display_name_for_role("root") == "项目主管"
    assert display_name_for_role("pro") == "方案主张"
    assert display_name_for_role("unknown-role") == "unknown-role"


def test_role_for_archetype_mapping() -> None:
    assert role_for_archetype("explore") == "explore"
    assert role_for_archetype("VERIFY") == "explore"
    assert role_for_archetype("custom-scout") == DEFAULT_JAILED_ROLE
    assert role_for_archetype("") == DEFAULT_JAILED_ROLE
    assert role_for_archetype("referee") == "referee"


def test_normalize_run_id() -> None:
    assert normalize_run_id(None) == DEFAULT_RUN_ID
    assert normalize_run_id("  ") == DEFAULT_RUN_ID
    assert normalize_run_id("r1") == "r1"


def test_proposals_root_uses_shared_path_parts(tmp_path: Path) -> None:
    root = proposals_root(run_id="run-1", workspace=tmp_path)
    expected = tmp_path.joinpath(*PROPOSALS_REL_PARTS, "run-1").resolve()
    assert root == expected


def test_proposals_root_falls_back_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = proposals_root(run_id="h1", workspace=None)
    assert root == tmp_path.joinpath(*PROPOSALS_REL_PARTS, "h1").resolve()


def test_worker_may_write_proposals_only(tmp_path: Path) -> None:
    run_id = "r1"
    draft = proposals_root(run_id=run_id, workspace=tmp_path) / "a.py"
    business = tmp_path / "src" / "a.py"
    with write_gate_scope(role="worker", run_id=run_id, workspace=tmp_path):
        assert_write_allowed(draft)
        with pytest.raises(WriteGateError, match="只能写入草稿目录"):
            assert_write_allowed(business)


def test_nested_proposals_path_allowed(tmp_path: Path) -> None:
    run_id = "nest"
    nested = proposals_root(run_id=run_id, workspace=tmp_path) / "dir" / "x.py"
    with write_gate_scope(role="worker", run_id=run_id, workspace=tmp_path):
        assert_write_allowed(nested)


def test_sibling_lumina_dir_not_proposals(tmp_path: Path) -> None:
    """`.lumina/other/{run}` must not count as proposals jail."""
    run_id = "r"
    fake = tmp_path / ".lumina" / "other" / run_id / "x.py"
    with write_gate_scope(role="worker", run_id=run_id, workspace=tmp_path):
        with pytest.raises(WriteGateError):
            assert_write_allowed(fake)


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
        assert is_landing_role("referee")
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


def test_jailed_role_without_run_id_denied(tmp_path: Path) -> None:
    with write_gate_scope(role="worker", run_id=None, workspace=tmp_path):
        with pytest.raises(WriteGateError, match="缺少 run_id"):
            assert_write_allowed(tmp_path / "x.py")


def test_is_proposals_path(tmp_path: Path) -> None:
    run_id = "z"
    inside = proposals_root(run_id=run_id, workspace=tmp_path) / "f.txt"
    assert is_proposals_path(inside, run_id=run_id, workspace=tmp_path)
    assert not is_proposals_path(tmp_path / "f.txt", run_id=run_id, workspace=tmp_path)


def test_write_gate_scope_restores_previous(tmp_path: Path) -> None:
    with write_gate_scope(role="worker", run_id="outer", workspace=tmp_path):
        assert get_write_gate().role == "worker"
        with write_gate_scope(role="pro", run_id="inner", workspace=tmp_path):
            assert get_write_gate().role == "pro"
        assert get_write_gate().role == "worker"
    assert get_write_gate().role == "root"
    assert get_write_gate().run_id is None


def test_subagent_write_gate_scope_maps_verify(tmp_path: Path) -> None:
    with subagent_write_gate_scope(
        archetype="verify",
        run_id="v1",
        workspace=tmp_path,
    ) as ctx:
        assert ctx.role == "explore"
        draft = proposals_root(run_id="v1", workspace=tmp_path) / "note.md"
        assert_write_allowed(draft)


def test_write_tool_respects_gate(tmp_path: Path) -> None:
    from secretary.agent.tools.fs import WriteTool

    tool = WriteTool()
    business = tmp_path / "secret.py"
    draft = proposals_root(run_id="tool-run", workspace=tmp_path) / "secret.py"
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


def test_edit_tool_respects_gate(tmp_path: Path) -> None:
    from secretary.agent.p0_tools import EditTool

    business = tmp_path / "app.py"
    business.write_text("old\n", encoding="utf-8")
    draft = proposals_root(run_id="e1", workspace=tmp_path) / "app.py"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("old\n", encoding="utf-8")
    tool = EditTool()
    with write_gate_scope(role="worker", run_id="e1", workspace=tmp_path):
        denied = tool.execute(
            {"path": str(business), "oldText": "old", "newText": "new"},
            tmp_path,
        )
        assert "WriteGate" in str(denied)
        ok = tool.execute(
            {"path": str(draft), "oldText": "old", "newText": "new"},
            tmp_path,
        )
        assert str(ok).startswith("OK:")
        assert draft.read_text(encoding="utf-8") == "new\n"


def test_delete_tool_respects_gate(tmp_path: Path) -> None:
    from secretary.agent.tools.fs import FileDeleteTool

    business = tmp_path / "gone.py"
    business.write_text("x\n", encoding="utf-8")
    draft = proposals_root(run_id="d1", workspace=tmp_path) / "gone.py"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("x\n", encoding="utf-8")
    tool = FileDeleteTool()
    with write_gate_scope(role="worker", run_id="d1", workspace=tmp_path):
        denied = tool.execute({"path": str(business)}, tmp_path)
        assert "WriteGate" in str(denied)
        assert business.exists()
        ok = tool.execute({"path": str(draft)}, tmp_path)
        assert str(ok).startswith("OK:")
        assert not draft.exists()


def test_move_tool_respects_gate(tmp_path: Path) -> None:
    from secretary.agent.tools.fs import MoveTool

    src = tmp_path / "a.py"
    dst = tmp_path / "b.py"
    src.write_text("x\n", encoding="utf-8")
    tool = MoveTool()
    with write_gate_scope(role="worker", run_id="m1", workspace=tmp_path):
        denied = tool.execute(
            {"from_path": str(src), "to_path": str(dst)},
            tmp_path,
        )
        assert "WriteGate" in str(denied)
        assert src.exists()
