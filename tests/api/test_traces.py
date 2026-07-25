"""FR-51: trace API load + JSONL export."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from secretary.agent.progress_events import ProgressEvent
from secretary.agent.trace_store import TraceStore
from secretary.api.app import app


def test_trace_get_and_export(tmp_path: Path, monkeypatch) -> None:
    store = TraceStore(tmp_path / "traces")
    store.append(
        "trace-api-1",
        ProgressEvent(
            kind="turn_started",
            iteration=0,
            message="hi",
            turn_id="turn_1",
            thread_id="th_1",
        ),
        retention="full",
    )
    app.state.trace_store = store
    client = TestClient(app)
    resp = client.get("/api/chat/traces/trace-api-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["nodes"][0]["kind"] == "turn_started"

    export = client.get("/api/chat/traces/trace-api-1/export")
    assert export.status_code == 200
    assert "turn_started" in export.text
    assert "application/x-ndjson" in export.headers.get("content-type", "")
