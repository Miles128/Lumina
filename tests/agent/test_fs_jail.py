"""Tests for hard write jail + full_fs_access."""

from __future__ import annotations

from pathlib import Path

import pytest

from secretary.agent.artifact_paths import collect_artifact_paths
from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.fs_jail import (
    FsJailError,
    assert_writable,
    full_fs_access_scope,
    shell_escapes_jail,
)
from secretary.agent.harness_config import apply_permission_mode
from secretary.agent.tools.code_exec import CodeExecTool
from secretary.agent.tools.fs import WriteTool
from secretary.agent.tools.shell import ShellTool


def test_assert_writable_blocks_outside(tmp_path: Path) -> None:
    jail = tmp_path / "sandbox"
    jail.mkdir()
    outside = tmp_path / "outside.txt"
    with full_fs_access_scope(False):
        with pytest.raises(FsJailError):
            assert_writable(outside, jail)
        ok = assert_writable(jail / "ok.txt", jail)
        assert ok.is_relative_to(jail.resolve())


def test_assert_writable_allows_full_fs(tmp_path: Path) -> None:
    jail = tmp_path / "sandbox"
    jail.mkdir()
    outside = tmp_path / "outside.txt"
    with full_fs_access_scope(True):
        resolved = assert_writable(outside, jail)
        assert resolved == outside.resolve()


def test_write_tool_respects_jail(tmp_path: Path) -> None:
    jail = tmp_path / "sandbox"
    jail.mkdir()
    tool = WriteTool()
    with full_fs_access_scope(False):
        result = tool.execute(
            {"path": str(tmp_path / "escape.txt"), "content": "x"},
            jail,
        )
        assert hasattr(result, "success")
        assert result.success is False
        assert "sandbox" in str(result.error).lower() or "working directory" in str(result.error)

        ok = tool.execute({"path": "inside.txt", "content": "hi"}, jail)
        assert isinstance(ok, str) or (hasattr(ok, "success") and ok.success)
        assert (jail / "inside.txt").read_text(encoding="utf-8") == "hi"


def test_shell_escapes_jail_detects_absolute(tmp_path: Path) -> None:
    jail = tmp_path / "sb"
    jail.mkdir()
    with full_fs_access_scope(False):
        err = shell_escapes_jail(f"echo hi > {tmp_path / 'leak.txt'}", jail)
        assert err is not None
        assert shell_escapes_jail("echo hi > ./ok.txt", jail) is None
        assert shell_escapes_jail("cat /dev/null", jail) is None


def test_shell_tool_blocks_escape(tmp_path: Path) -> None:
    jail = tmp_path / "sb"
    jail.mkdir()
    tool = ShellTool()
    with full_fs_access_scope(False):
        result = tool.execute(
            {"command": f"echo x > {tmp_path / 'out.txt'}"},
            jail,
        )
        assert result.success is False


def test_hard_sandbox_skips_confirm_for_write_and_code_exec(tmp_path: Path) -> None:
    jail = tmp_path / "sb"
    jail.mkdir()
    require = apply_permission_mode("normal")
    with full_fs_access_scope(False):
        needs, _ = tool_requires_confirmation(
            WriteTool(),
            {"path": "a.txt", "content": "x"},
            working_dir=jail,
            file_auth=None,
            require_confirm=require,
        )
        assert needs is False

        needs, _ = tool_requires_confirmation(
            CodeExecTool(),
            {"code": "print(1)"},
            working_dir=jail,
            file_auth=None,
            require_confirm=require,
        )
        assert needs is False

        needs, kind = tool_requires_confirmation(
            ShellTool(),
            {"command": "touch x.txt"},
            working_dir=jail,
            file_auth=None,
            require_confirm=require,
        )
        assert needs is True
        assert kind == "shell"


def test_full_fs_restores_confirm_policy(tmp_path: Path) -> None:
    jail = tmp_path / "sb"
    jail.mkdir()
    require = apply_permission_mode("normal")
    with full_fs_access_scope(True):
        needs, kind = tool_requires_confirmation(
            WriteTool(),
            {"path": "a.txt", "content": "x"},
            working_dir=jail,
            file_auth=None,
            require_confirm=require,
        )
        assert needs is True
        assert kind == "write_new"


def test_collect_artifact_paths_from_write(tmp_path: Path) -> None:
    path = tmp_path / "report.xlsx"
    path.write_bytes(b"PK")
    paths = collect_artifact_paths(
        "write",
        {"path": str(path), "content": "x"},
        tmp_path,
        success=True,
    )
    assert paths == [str(path.resolve())]


def test_full_fs_access_persisted(tmp_path: Path) -> None:
    from secretary.config import Settings
    from secretary.services.agent_config import AgentConfigStore

    store = AgentConfigStore(tmp_path / "agent.json")
    assert store.load().full_fs_access is False
    store.update({"full_fs_access": True})
    view = store.get_view(Settings(data_dir=tmp_path / "data"))
    assert view.full_fs_access is True
