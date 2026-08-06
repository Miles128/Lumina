"""Tests for chat uploads and attachment context."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.services.chat_uploads import (
    copy_local_path,
    format_attachments_block,
    remove_thread_uploads,
    save_upload_bytes,
    thread_upload_dir_for_cleanup,
    uploads_root,
)


def test_save_upload_bytes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    saved = save_upload_bytes(
        data_dir,
        thread_id="t1",
        filename="报告.xlsx",
        content=b"hello",
    )
    assert saved.name == "报告.xlsx"
    assert Path(saved.path).read_bytes() == b"hello"
    assert saved.size == 5


def test_copy_local_path(tmp_path: Path) -> None:
    src = tmp_path / "note.docx"
    src.write_bytes(b"docx-bytes")
    saved = copy_local_path(tmp_path / "data", thread_id="t2", source=src)
    assert saved.name == "note.docx"
    assert Path(saved.path).read_bytes() == b"docx-bytes"


def test_format_attachments_block(tmp_path: Path) -> None:
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF")
    block = format_attachments_block([str(f)])
    assert "read_document" in block
    assert "a.pdf" in block
    assert str(f.resolve()) in block


def test_remove_thread_uploads(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    save_upload_bytes(data_dir, thread_id="t_del", filename="a.txt", content=b"x")
    assert (uploads_root(data_dir) / "t_del").is_dir()
    assert remove_thread_uploads(data_dir, "t_del") is True
    assert not (uploads_root(data_dir) / "t_del").exists()
    assert remove_thread_uploads(data_dir, "t_del") is False


def test_thread_upload_dir_for_cleanup_rejects_unsafe_ids(tmp_path: Path) -> None:
    assert thread_upload_dir_for_cleanup(tmp_path / "data", "") is None
    path = thread_upload_dir_for_cleanup(tmp_path / "data", "../escape")
    assert path is not None
    assert path.is_relative_to(uploads_root(tmp_path / "data").resolve())


def test_upload_endpoints(tmp_path: Path, monkeypatch) -> None:
    from secretary import config

    monkeypatch.setattr(config.settings, "data_dir", tmp_path / "data")
    client = TestClient(app)
    response = client.post(
        "/api/chat/uploads",
        data={"thread_id": "th1"},
        files=[("files", ("hello.txt", b"abc", "text/plain"))],
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["files"]) == 1
    assert payload["files"][0]["name"] == "hello.txt"
    assert Path(payload["files"][0]["path"]).read_bytes() == b"abc"

    src = tmp_path / "local.pdf"
    src.write_bytes(b"%PDF-1.4")
    response2 = client.post(
        "/api/chat/uploads/from-paths",
        json={"thread_id": "th1", "paths": [str(src)]},
    )
    assert response2.status_code == 200
    assert response2.json()["files"][0]["name"] == "local.pdf"
