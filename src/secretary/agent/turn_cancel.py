"""Turn cancellation registry keyed by trace_id."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_events: dict[str, threading.Event] = {}


def begin_turn(trace_id: str) -> threading.Event:
    event = threading.Event()
    with _lock:
        _events[trace_id] = event
    return event


def request_cancel(trace_id: str) -> bool:
    with _lock:
        event = _events.get(trace_id)
    if event is None:
        return False
    event.set()
    return True


def is_cancelled(trace_id: str) -> bool:
    with _lock:
        event = _events.get(trace_id)
    return bool(event and event.is_set())


def end_turn(trace_id: str) -> None:
    with _lock:
        _events.pop(trace_id, None)
