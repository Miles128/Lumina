"""Permission mode + require_confirm confirmation policy."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.confirmation_policy import tool_requires_confirmation
from secretary.agent.harness_config import (
    ConfirmRequireConfig,
    HarnessConfig,
    apply_permission_mode,
    infer_permission_mode,
)
from secretary.agent.policy_view import build_policy_view, resolve_policy_update
from secretary.agent.tools.code_exec import CodeExecTool
from secretary.agent.tools.fs import FileDeleteTool, FileWriteTool
from secretary.agent.tools.shell import ShellTool
from secretary.services.file_auth import FileAuthService


def test_apply_and_infer_permission_modes() -> None:
    assert infer_permission_mode(apply_permission_mode("normal")) == "normal"
    assert infer_permission_mode(apply_permission_mode("auto")) == "auto"
    assert infer_permission_mode(apply_permission_mode("yolo")) == "yolo"
    custom = ConfirmRequireConfig(write_new=False, shell=True)
    assert infer_permission_mode(custom) == "custom"


def test_yolo_skips_write_shell_action(tmp_path: Path) -> None:
    cwd = tmp_path
    require = apply_permission_mode("yolo")
    write = FileWriteTool()
    needs, kind = tool_requires_confirmation(
        write,
        {"path": "new.txt", "content": "x"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is False
    assert kind == ""

    shell = ShellTool()
    needs, _ = tool_requires_confirmation(
        shell,
        {"command": "rm -rf /tmp/lumina_yolo_test"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is False

    needs, _ = tool_requires_confirmation(
        CodeExecTool(),
        {"code": "print(1)"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is False


def test_auto_skips_new_write_keeps_modify_and_shell(tmp_path: Path) -> None:
    cwd = tmp_path
    (cwd / "old.txt").write_text("old", encoding="utf-8")
    require = apply_permission_mode("auto")
    write = FileWriteTool()

    needs, _ = tool_requires_confirmation(
        write,
        {"path": "brand_new.txt", "content": "x"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is False

    needs, kind = tool_requires_confirmation(
        write,
        {"path": "old.txt", "content": "y"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is True
    assert kind == "write_modify"

    needs, kind = tool_requires_confirmation(
        ShellTool(),
        {"command": "rm -rf /tmp/x"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is True
    assert kind == "shell"

    needs, _ = tool_requires_confirmation(
        FileDeleteTool(),
        {"path": "old.txt"},
        working_dir=cwd,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is True


def test_normal_still_confirms_new_write(tmp_path: Path) -> None:
    require = apply_permission_mode("normal")
    needs, kind = tool_requires_confirmation(
        FileWriteTool(),
        {"path": "a.txt", "content": "x"},
        working_dir=tmp_path,
        file_auth=None,
        require_confirm=require,
        full_fs_access=True,
    )
    assert needs is True
    assert kind == "write_new"


def test_resolve_policy_update_mode_applies_grants(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "auth.json")
    current = HarnessConfig()
    updated, mode = resolve_policy_update(
        current=current,
        permission_mode="auto",
        require_confirm=None,
        session_grants=None,
        file_auth=auth,
    )
    assert mode == "auto"
    assert updated.require_confirm.write_new is False
    assert updated.require_confirm.action is False
    assert auth.has_session_write_new() is True
    assert auth.has_session_code_exec() is True

    updated, mode = resolve_policy_update(
        current=updated,
        permission_mode="yolo",
        require_confirm=None,
        session_grants=None,
        file_auth=auth,
    )
    assert mode == "yolo"
    assert auth.has_permanent_read() is True

    updated, mode = resolve_policy_update(
        current=updated,
        permission_mode="normal",
        require_confirm=None,
        session_grants=None,
        file_auth=auth,
    )
    assert mode == "normal"
    assert auth.has_session_write_new() is False
    assert auth.has_session_code_exec() is False
    # permanent_read is not force-cleared on normal
    assert auth.has_permanent_read() is True


def test_build_policy_view_includes_editable_fields(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "auth.json")
    harness = HarnessConfig(
        permission_mode="auto",
        require_confirm=apply_permission_mode("auto"),
    )
    view = build_policy_view(auth, harness=harness)
    assert view["editable"] is True
    assert view["permission_mode"] == "auto"
    assert view["require_confirm"]["write_new"] is False
    assert view["require_confirm"]["write_modify"] is True
