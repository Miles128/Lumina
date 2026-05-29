"""Tests for file authorization service."""

from pathlib import Path

from secretary.services.file_auth import FileAuthService


def test_permanent_read_skips_future_read_confirmation(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    assert auth.needs_read_confirmation() is True
    auth.grant_permanent_read()
    assert auth.has_permanent_read() is True
    assert auth.needs_read_confirmation() is False

    auth.revoke_permanent_read()
    assert auth.needs_read_confirmation() is True


def test_session_write_only_applies_to_new_files(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    new_file = tmp_path / "notes.txt"
    existing = tmp_path / "existing.txt"
    existing.write_text("old", encoding="utf-8")

    assert auth.needs_write_confirmation(new_file, append=False) is True
    auth.grant_session_write_new()
    assert auth.needs_write_confirmation(new_file, append=False) is False
    assert auth.needs_write_confirmation(existing, append=False) is True
    assert auth.needs_write_confirmation(existing, append=True) is True


def test_write_kind_classification(tmp_path: Path) -> None:
    auth = FileAuthService(tmp_path / "file_auth.json")
    new_file = tmp_path / "new.txt"
    existing = tmp_path / "old.txt"
    existing.write_text("x", encoding="utf-8")

    assert auth.write_confirmation_kind(new_file, append=False) == "write_new"
    assert auth.write_confirmation_kind(existing, append=False) == "write_modify"
    assert auth.write_confirmation_kind(existing, append=True) == "write_modify"
