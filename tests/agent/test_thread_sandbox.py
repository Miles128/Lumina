"""Thread sandbox helper: per-thread default cwd under data_dir/sandbox."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.thread_sandbox import (
    clear_all,
    ensure,
    remove,
    safe_thread_id,
    sandbox_root,
)


def test_safe_thread_id_keeps_alnum_and_defaults_empty() -> None:
    assert safe_thread_id("t_abc123") == "t_abc123"
    assert safe_thread_id("") == "_default"
    assert safe_thread_id("   ") == "_default"
    # `/` replaced; `.` and `-` are allowed characters
    assert safe_thread_id("../evil/x") == ".._evil_x"
    assert safe_thread_id("a/b\\c") == "a_b_c"


def test_ensure_creates_dir_under_sandbox_root(tmp_path: Path) -> None:
    root = sandbox_root(tmp_path)
    path = ensure("t_sess1", tmp_path)
    assert path == (root / "t_sess1").resolve()
    assert path.is_dir()
    assert path.is_relative_to(root.resolve())


def test_ensure_empty_thread_uses_default(tmp_path: Path) -> None:
    path = ensure("", tmp_path)
    assert path.name == "_default"
    assert path.is_dir()


def test_remove_deletes_thread_sandbox(tmp_path: Path) -> None:
    path = ensure("t_del", tmp_path)
    (path / "note.txt").write_text("x", encoding="utf-8")
    remove("t_del", tmp_path)
    assert not path.exists()


def test_remove_missing_is_noop(tmp_path: Path) -> None:
    remove("never_created", tmp_path)


def test_clear_all_removes_every_thread_sandbox(tmp_path: Path) -> None:
    ensure("t_a", tmp_path)
    ensure("t_b", tmp_path)
    (ensure("t_a", tmp_path) / "note.txt").write_text("x", encoding="utf-8")
    removed = clear_all(tmp_path)
    assert removed == 2
    assert not (sandbox_root(tmp_path) / "t_a").exists()
    assert not (sandbox_root(tmp_path) / "t_b").exists()
    # Root itself is preserved.
    assert sandbox_root(tmp_path).is_dir()


def test_clear_all_missing_root_is_noop(tmp_path: Path) -> None:
    assert clear_all(tmp_path / "absent") == 0


def test_sandbox_clear_endpoint(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from secretary import config
    from secretary.agent import thread_sandbox
    from secretary.api.app import app

    monkeypatch.setattr(config.settings, "data_dir", tmp_path / "data")
    thread_sandbox.ensure("t_a", tmp_path / "data")
    thread_sandbox.ensure("t_b", tmp_path / "data")
    client = TestClient(app)
    response = client.delete("/api/sandbox")
    assert response.status_code == 200
    assert response.json()["removed"] == 2
    assert not (sandbox_root(tmp_path / "data") / "t_a").exists()


def test_ensure_path_stays_inside_sandbox(tmp_path: Path) -> None:
    path = ensure("../../outside", tmp_path)
    root = sandbox_root(tmp_path).resolve()
    assert path.resolve().is_relative_to(root)
    assert "outside" in path.name or path.name.startswith("_")
