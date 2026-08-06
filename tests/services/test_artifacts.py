"""Tests for artifact browser (tree + preview)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.services import artifacts as artifact_service
from secretary.services.agent_config import AgentConfigStore


def test_list_tree_and_preview_markdown(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    store = AgentConfigStore(data / "agent.json")
    sandbox = artifact_service.allowed_roots(
        data_dir=data, thread_id="t1", agent_config=store
    )[0]["path"]
    note = Path(sandbox) / "notes" / "a.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Hello\n\nworld", encoding="utf-8")

    tree = artifact_service.list_tree(
        sandbox,
        data_dir=data,
        thread_id="t1",
        agent_config=store,
        depth=3,
    )
    assert any(e["name"] == "a.md" for e in tree["entries"])

    preview = artifact_service.preview_file(
        str(note),
        data_dir=data,
        thread_id="t1",
        agent_config=store,
    )
    assert preview["kind"] == "markdown"
    assert "Hello" in preview["text"]


def test_rejects_path_outside_roots(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    store = AgentConfigStore(data / "agent.json")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    # Outside home for this tmp path — should fail tree_only and may fail preview
    # if not under home. Force by using a path not under home/data.
    with pytest.raises(PermissionError):
        artifact_service.list_tree(
            str(tmp_path),
            data_dir=data,
            thread_id="t1",
            agent_config=store,
        )


def test_artifacts_api_context() -> None:
    client = TestClient(app)
    resp = client.get("/api/artifacts/context", params={"thread_id": "api-t1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sandbox"]
    assert any(r.get("id") == "sandbox" for r in body["roots"])


def test_preview_kinds_md_html(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    store = AgentConfigStore(data / "agent.json")
    sandbox = Path(
        artifact_service.allowed_roots(data_dir=data, thread_id="k1", agent_config=store)[0]["path"]
    )
    md = sandbox / "a.md"
    md.write_text("# Title\n\nbody", encoding="utf-8")
    html = sandbox / "b.html"
    html.write_text("<html><body><h1>Hi</h1></body></html>", encoding="utf-8")
    assert artifact_service.preview_file(str(md), data_dir=data, thread_id="k1", agent_config=store)[
        "kind"
    ] == "markdown"
    assert artifact_service.preview_file(str(html), data_dir=data, thread_id="k1", agent_config=store)[
        "kind"
    ] == "html"


def test_artifacts_api_raw_pdf_bytes(tmp_path: Path) -> None:
    client = TestClient(app)
    ctx = client.get("/api/artifacts/context", params={"thread_id": "raw-t1"}).json()
    sandbox = Path(ctx["sandbox"])
    pdf = sandbox / "tiny.pdf"
    # Minimal PDF header is enough for FileResponse; preview extract may be empty.
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    meta = client.get(
        "/api/artifacts/file",
        params={"path": str(pdf), "thread_id": "raw-t1"},
    )
    assert meta.status_code == 200
    assert meta.json()["kind"] == "pdf"
    raw = client.get(
        "/api/artifacts/raw",
        params={"path": str(pdf), "thread_id": "raw-t1"},
    )
    assert raw.status_code == 200
    assert raw.content.startswith(b"%PDF")
    pdf.unlink(missing_ok=True)
