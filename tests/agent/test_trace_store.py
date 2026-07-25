"""FR-51: reasoning / run trace persistence and export."""

from __future__ import annotations

from pathlib import Path

from secretary.agent.progress_events import ProgressEvent
from secretary.agent.trace_store import TraceStore


def test_append_and_load_nodes(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "traces")
    store.append(
        "trace-1",
        ProgressEvent(
            kind="turn_started",
            iteration=0,
            message="hello",
            turn_id="turn_abc",
            thread_id="th_1",
        ),
        retention="full",
    )
    store.append(
        "trace-1",
        ProgressEvent(
            kind="tool_started",
            iteration=1,
            tool_name="file_read",
            detail="reading foo.py",
            turn_id="turn_abc",
            thread_id="th_1",
        ),
        retention="full",
    )
    nodes = store.load("trace-1")
    assert len(nodes) == 2
    assert nodes[0]["kind"] == "turn_started"
    assert nodes[0]["trace_id"] == "trace-1"
    assert nodes[0]["turn_id"] == "turn_abc"
    assert nodes[1]["tool_name"] == "file_read"


def test_retention_off_skips_writes(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "traces")
    store.append(
        "trace-off",
        ProgressEvent(kind="turn_started", iteration=0, message="x"),
        retention="off",
    )
    assert store.load("trace-off") == []


def test_summary_retention_truncates_detail(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "traces")
    long_detail = "x" * 500
    store.append(
        "trace-sum",
        ProgressEvent(
            kind="tool_finished",
            iteration=1,
            tool_name="shell",
            detail=long_detail,
            success=True,
        ),
        retention="summary",
    )
    nodes = store.load("trace-sum")
    assert len(nodes) == 1
    assert len(nodes[0]["detail"]) <= 200


def test_export_jsonl(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "traces")
    store.append(
        "trace-ex",
        ProgressEvent(kind="final_reply", iteration=2, message="done"),
        retention="full",
    )
    text = store.export_jsonl("trace-ex")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert '"kind": "final_reply"' in lines[0] or '"kind":"final_reply"' in lines[0]


def test_skip_reply_delta_noise(tmp_path: Path) -> None:
    store = TraceStore(tmp_path / "traces")
    store.append(
        "trace-d",
        ProgressEvent(kind="reply_delta", iteration=1, message="tok"),
        retention="full",
    )
    store.append(
        "trace-d",
        ProgressEvent(kind="reply_end", iteration=1, message="full"),
        retention="full",
    )
    nodes = store.load("trace-d")
    assert len(nodes) == 1
    assert nodes[0]["kind"] == "reply_end"
