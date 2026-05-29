"""Thread-safe progress channel hub for chat SSE streaming."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass

from secretary.agent.progress_events import ProgressEvent, progress_event_payload


@dataclass
class _Channel:
    events: queue.Queue[ProgressEvent | None]
    closed: bool = False


class ProgressHub:
    """Publish agent loop progress events keyed by client trace id."""

    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}
        self._lock = threading.Lock()

    def open(self, trace_id: str) -> None:
        if not trace_id:
            return
        with self._lock:
            self._channels[trace_id] = _Channel(events=queue.Queue())

    def publish(self, trace_id: str, event: ProgressEvent) -> None:
        if not trace_id:
            return
        with self._lock:
            channel = self._channels.get(trace_id)
        if channel is None or channel.closed:
            return
        channel.events.put(event)

    def close(self, trace_id: str) -> None:
        if not trace_id:
            return
        with self._lock:
            channel = self._channels.get(trace_id)
            if channel is None:
                return
            channel.closed = True
            channel.events.put(None)

    def discard(self, trace_id: str) -> None:
        if not trace_id:
            return
        with self._lock:
            self._channels.pop(trace_id, None)

    async def stream(self, trace_id: str) -> AsyncIterator[str]:
        channel = await self._wait_for_channel(trace_id)
        if channel is None:
            yield _sse({"kind": "error", "label": "进度通道不存在或已过期"})
            return
        try:
            while True:
                try:
                    event = await asyncio.to_thread(channel.events.get, True, 180)
                except queue.Empty:
                    yield _sse({"kind": "error", "label": "进度等待超时"})
                    break
                if event is None:
                    yield _sse({"kind": "done", "label": "完成"})
                    break
                yield _sse(progress_event_payload(event))
        finally:
            self.discard(trace_id)

    async def _wait_for_channel(self, trace_id: str) -> _Channel | None:
        for _ in range(100):
            with self._lock:
                channel = self._channels.get(trace_id)
            if channel is not None:
                return channel
            await asyncio.sleep(0.05)
        return None


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
