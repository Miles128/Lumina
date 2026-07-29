"""FR-51: durable reasoning / run traces (local JSONL per trace_id)."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Literal

from secretary.agent.progress_events import ProgressEvent, progress_event_label

logger = logging.getLogger(__name__)

TraceRetention = Literal["full", "summary", "off"]

_SKIP_KINDS = frozenset({"reply_delta", "iteration_started", "iteration_completed"})
_SUMMARY_DETAIL_MAX = 200
_SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class TraceStore:
    """Append-only local store under ``{root}/{trace_id}.jsonl``."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        trace_id: str,
        event: ProgressEvent,
        *,
        retention: TraceRetention = "full",
    ) -> None:
        if retention == "off":
            return
        if not trace_id or event.kind in _SKIP_KINDS:
            return
        path = self._path_for(trace_id)
        if path is None:
            return
        node = self._node_from_event(trace_id, event, retention=retention)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(node, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.debug("trace append failed for %s: %s", trace_id, exc)

    def load(self, trace_id: str) -> list[dict[str, Any]]:
        path = self._path_for(trace_id)
        if path is None or not path.is_file():
            return []
        nodes: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    nodes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError as exc:
            logger.debug("trace load failed for %s: %s", trace_id, exc)
        return nodes

    def export_jsonl(self, trace_id: str) -> str:
        path = self._path_for(trace_id)
        if path is None or not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def prune(self, *, retain_days: int) -> int:
        """Delete trace files older than ``retain_days``. ``0`` means keep forever."""
        if retain_days <= 0:
            return 0
        cutoff = time.time() - retain_days * 86400
        removed = 0
        for path in self._root.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def _path_for(self, trace_id: str) -> Path | None:
        cleaned = trace_id.strip()
        if not _SAFE_TRACE_ID.match(cleaned):
            logger.debug("reject unsafe trace_id: %r", trace_id)
            return None
        # Avoid path separators even if regex drifts.
        safe = cleaned.replace("/", "_").replace("\\", "_")
        return self._root / f"{safe}.jsonl"

    def _node_from_event(
        self,
        trace_id: str,
        event: ProgressEvent,
        *,
        retention: TraceRetention,
    ) -> dict[str, Any]:
        detail = event.detail or ""
        message = event.message or ""
        if retention == "summary":
            detail = detail[:_SUMMARY_DETAIL_MAX]
            message = message[:_SUMMARY_DETAIL_MAX]
        return {
            "ts": time.time(),
            "trace_id": trace_id,
            "turn_id": event.turn_id,
            "thread_id": event.thread_id,
            "item_id": event.item_id,
            "parent_turn_id": event.parent_turn_id,
            "kind": event.kind,
            "iteration": event.iteration,
            "tool_name": event.tool_name,
            "success": event.success,
            "message": message,
            "detail": detail,
            "label": progress_event_label(event),
            "sub_run_id": event.sub_run_id,
            "archetype": event.archetype,
            "goal": event.goal,
            "subagent_status": event.subagent_status,
            "latency_ms": event.latency_ms,
            "prompt_tokens": event.prompt_tokens,
            "completion_tokens": event.completion_tokens,
            "error_type": event.error_type,
            "idp": event.idp,
        }
