"""Feishu connector via lark-cli."""

from __future__ import annotations

from secretary.connectors.base import BaseConnector
from secretary.core.types import MemoryChunk, SourceKind
from secretary.exceptions import ConnectorError
from secretary.memory.ingest import chunk_text


class FeishuConnector(BaseConnector):
    source = SourceKind.FEISHU

    def is_configured(self) -> bool:
        try:
            raw = self.run_command(["lark-cli", "auth", "status"], timeout=10)
            payload = self.parse_json_output(raw)
            return isinstance(payload, dict) and payload.get("ok") is True
        except ConnectorError:
            return False

    def fetch(self) -> list[MemoryChunk]:
        chunks: list[MemoryChunk] = []
        chunks.extend(self._fetch_calendar())
        chunks.extend(self._fetch_tasks())
        return chunks

    def _fetch_calendar(self) -> list[MemoryChunk]:
        raw = self.run_command(["lark-cli", "calendar", "+agenda", "--format", "json"])
        payload = self.parse_json_output(raw)
        events = payload if isinstance(payload, list) else []
        chunks: list[MemoryChunk] = []
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            title = str(event.get("summary") or event.get("title") or f"日程 {index + 1}")
            body = _format_event(event)
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=f"calendar:{title}:{index}",
                    title=f"飞书日程 · {title}",
                    body=body,
                    metadata={"kind": "calendar"},
                )
            )
        return chunks

    def _fetch_tasks(self) -> list[MemoryChunk]:
        raw = self.run_command(
            ["lark-cli", "task", "+get-my-tasks", "--format", "json"],
            timeout=90,
        )
        payload = self.parse_json_output(raw)
        tasks = payload if isinstance(payload, list) else []
        chunks: list[MemoryChunk] = []
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                continue
            title = str(task.get("summary") or task.get("title") or f"任务 {index + 1}")
            body = _format_task(task)
            chunks.extend(
                chunk_text(
                    source=self.source,
                    key=f"task:{title}:{index}",
                    title=f"飞书任务 · {title}",
                    body=body,
                    metadata={"kind": "task"},
                )
            )
        return chunks


def _format_event(event: dict[str, object]) -> str:
    lines = [
        f"标题: {event.get('summary') or event.get('title') or '未命名'}",
        f"开始: {event.get('start_time') or event.get('start') or ''}",
        f"结束: {event.get('end_time') or event.get('end') or ''}",
        f"地点: {event.get('location') or ''}",
        f"描述: {event.get('description') or ''}",
    ]
    return "\n".join(str(line) for line in lines if not str(line).endswith(": "))


def _format_task(task: dict[str, object]) -> str:
    lines = [
        f"标题: {task.get('summary') or task.get('title') or '未命名'}",
        f"截止: {task.get('due_time') or task.get('due') or ''}",
        f"状态: {task.get('status') or ''}",
        f"备注: {task.get('description') or ''}",
    ]
    return "\n".join(str(line) for line in lines if not str(line).endswith(": "))
