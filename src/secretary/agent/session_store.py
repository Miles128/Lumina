"""Active turn registry + optional disk persistence (~/.lumina/turns.json)."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from secretary.agent.llm_config import LlmConfig
from secretary.agent.loop import PendingConfirmation, StepResult
from secretary.agent.subagent.resume import ParentTurnResumeState, SubAgentResumeState
from secretary.agent.tools.base import Tool, ToolCall
from secretary.agent.turn_models import TurnContext, TurnStatus

PauseKind = Literal["confirmation", "subagent", "parent_resume"]

_PAUSE_KINDS: tuple[PauseKind, ...] = ("confirmation", "subagent", "parent_resume")


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_pause_entry(raw: Any) -> dict[PauseKind, dict[str, Any]]:
    """Upgrade legacy `{kind, data}` or multi-kind map into `{kind: data, ...}`."""
    if not isinstance(raw, dict):
        return {}
    # Legacy single-kind: {"kind": "...", "data": {...}}
    legacy_kind = raw.get("kind")
    legacy_data = raw.get("data")
    if legacy_kind in _PAUSE_KINDS and isinstance(legacy_data, dict) and "kinds" not in raw:
        return {cast(PauseKind, legacy_kind): legacy_data}
    entry: dict[PauseKind, dict[str, Any]] = {}
    for kind in _PAUSE_KINDS:
        data = raw.get(kind)
        if isinstance(data, dict):
            entry[kind] = data
    return entry


def _pause_entry_to_disk(entry: dict[PauseKind, dict[str, Any]]) -> dict[str, Any]:
    kinds = [kind for kind in _PAUSE_KINDS if kind in entry]
    payload: dict[str, Any] = {"kinds": kinds}
    for kind in kinds:
        payload[kind] = entry[kind]
    return payload


def _pending_from_dict(raw: dict[str, Any]) -> PendingConfirmation:
    return PendingConfirmation(
        action_id=str(raw.get("action_id") or ""),
        tool_name=str(raw.get("tool_name") or ""),
        arguments=_dict_or_empty(raw.get("arguments")),
        description=str(raw.get("description") or ""),
        risk_level=str(raw.get("risk_level") or "medium"),
        confirmation_kind=str(raw.get("confirmation_kind") or "action"),
    )


def _step_from_dict(raw: Any) -> StepResult | None:
    if not isinstance(raw, dict):
        return None
    tool_call = None
    tool_raw = raw.get("tool_call")
    if isinstance(tool_raw, dict):
        tool_call = ToolCall(
            name=str(tool_raw.get("name") or ""),
            arguments=_dict_or_empty(tool_raw.get("arguments")),
            id=str(tool_raw.get("id") or ""),
        )
    return StepResult(
        thought=str(raw.get("thought") or ""),
        tool_call=tool_call,
        tool_output=str(raw.get("tool_output") or "") if raw.get("tool_output") is not None else None,
        needs_confirmation=bool(raw.get("needs_confirmation")),
        timestamp=str(raw.get("timestamp") or ""),
    )


def _to_json(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_json(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, list):
        return [_to_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_json(item) for item in value]
    return value


def pause_bundle_confirmation(
    *,
    pending: PendingConfirmation,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    return {"pending": _to_json(asdict(pending)), "messages": messages}


def pause_restore_confirmation(data: dict[str, Any]) -> tuple[PendingConfirmation, list[dict[str, str]]]:
    pending_raw = data.get("pending")
    messages_raw = data.get("messages")
    if not isinstance(pending_raw, dict) or not isinstance(messages_raw, list):
        raise ValueError("invalid confirmation pause bundle")
    return _pending_from_dict(pending_raw), [item for item in messages_raw if isinstance(item, dict)]


def pause_bundle_subagent(state: SubAgentResumeState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "archetype": state.archetype,
        "goal": state.goal,
        "context": state.context,
        "child_session_id": state.child_session_id,
        "parent_session_id": state.parent_session_id,
        "messages": state.messages,
        "max_steps": state.max_steps,
        "working_dir": str(state.working_dir),
        "pending": _to_json(asdict(state.pending)),
        "temperature": state.temperature,
        "pending_step": _to_json(asdict(state.pending_step)) if state.pending_step else None,
        "steps_completed": state.steps_completed,
        "used_tools": list(state.used_tools),
    }


def pause_restore_subagent(data: dict[str, Any], llm_config: LlmConfig) -> SubAgentResumeState:
    pending_raw = data.get("pending")
    if not isinstance(pending_raw, dict):
        raise ValueError("invalid subagent pause bundle")
    return SubAgentResumeState(
        run_id=str(data.get("run_id") or ""),
        archetype=str(data.get("archetype") or "explore"),
        goal=str(data.get("goal") or ""),
        context=str(data.get("context") or ""),
        child_session_id=str(data.get("child_session_id") or ""),
        parent_session_id=str(data.get("parent_session_id") or ""),
        messages=[item for item in data.get("messages", []) if isinstance(item, dict)],
        max_steps=int(data.get("max_steps") or 20),
        working_dir=Path(str(data.get("working_dir") or ".")),
        pending=_pending_from_dict(pending_raw),
        llm_config=llm_config,
        temperature=float(data.get("temperature") or 0.7),
        pending_step=_step_from_dict(data.get("pending_step")),
        steps_completed=int(data.get("steps_completed") or 0),
        used_tools=[str(item) for item in data.get("used_tools", []) if isinstance(item, str)],
    )


def pause_bundle_parent(state: ParentTurnResumeState) -> dict[str, Any]:
    return {
        "messages_snapshot": state.messages_snapshot,
        "tool_names": [tool.name for tool in state.tools],
        "max_steps": state.max_steps,
        "pending_step": _to_json(asdict(state.pending_step)),
        "assistant_message": state.assistant_message,
        "native_used": state.native_used,
        "step_idx": state.step_idx,
        "session_id": state.session_id,
        "user_message": state.user_message,
        "profile_excerpt": state.profile_excerpt,
        "memory_hits": state.memory_hits,
    }


def pause_restore_parent(
    data: dict[str, Any],
    *,
    llm_config: LlmConfig,
    tools: list[Tool],
) -> ParentTurnResumeState:
    pending_step = _step_from_dict(data.get("pending_step"))
    if pending_step is None:
        raise ValueError("invalid parent resume bundle")
    by_name = {tool.name: tool for tool in tools}
    tool_names = [str(name) for name in data.get("tool_names", []) if isinstance(name, str)]
    missing = [name for name in tool_names if name not in by_name]
    if missing:
        raise ValueError(f"parent resume tools missing after restart: {', '.join(missing)}")
    return ParentTurnResumeState(
        messages_snapshot=[item for item in data.get("messages_snapshot", []) if isinstance(item, dict)],
        tools=[by_name[name] for name in tool_names],
        max_steps=int(data.get("max_steps") or 20),
        pending_step=pending_step,
        assistant_message=data.get("assistant_message")
        if isinstance(data.get("assistant_message"), dict)
        else None,
        native_used=bool(data.get("native_used")),
        step_idx=int(data.get("step_idx") or 0),
        llm_config=llm_config,
        session_id=str(data.get("session_id") or ""),
        user_message=str(data.get("user_message") or ""),
        profile_excerpt=str(data.get("profile_excerpt") or ""),
        memory_hits=int(data.get("memory_hits") or 0),
    )


def _turn_to_dict(turn: TurnContext) -> dict[str, Any]:
    return {
        "turn_id": turn.turn_id,
        "trace_id": turn.trace_id,
        "thread_id": turn.thread_id,
        "user_message": turn.user_message,
        "parent_turn_id": turn.parent_turn_id,
        "child_id": turn.child_id,
        "status": turn.status,
        "started_at": turn.started_at,
        "item_seq": turn._item_seq,
    }


def _turn_from_dict(raw: dict[str, Any]) -> TurnContext | None:
    trace_id = str(raw.get("trace_id") or "").strip()
    turn_id = str(raw.get("turn_id") or "").strip()
    if not trace_id or not turn_id:
        return None
    status_raw = str(raw.get("status") or "running")
    status: TurnStatus = "running"
    if status_raw in {"running", "paused", "completed", "failed"}:
        status = cast(TurnStatus, status_raw)
    return TurnContext(
        turn_id=turn_id,
        trace_id=trace_id,
        thread_id=str(raw.get("thread_id") or ""),
        user_message=str(raw.get("user_message") or "")[:4000],
        parent_turn_id=str(raw.get("parent_turn_id") or ""),
        child_id=str(raw.get("child_id") or ""),
        status=status,
        started_at=str(raw.get("started_at") or datetime.now(UTC).isoformat()),
        _item_seq=int(raw.get("item_seq") or 0),
    )


class SessionStore:
    def __init__(self, *, persistence_path: Path | None = None) -> None:
        self._turns: dict[str, TurnContext] = {}
        self._lock = threading.Lock()
        self._path = persistence_path
        if persistence_path is not None:
            self._turns.update(self._load_turns())

    @property
    def persistence_path(self) -> Path | None:
        return self._path

    def start_turn(
        self,
        *,
        trace_id: str,
        thread_id: str = "",
        user_message: str = "",
        parent_turn_id: str = "",
        child_id: str = "",
    ) -> TurnContext:
        turn = TurnContext.create(
            trace_id=trace_id,
            thread_id=thread_id,
            user_message=user_message,
            parent_turn_id=parent_turn_id,
            child_id=child_id,
        )
        with self._lock:
            self._turns[trace_id] = turn
        self._save_turn(turn)
        return turn

    def get_turn(self, trace_id: str) -> TurnContext | None:
        if not trace_id:
            return None
        with self._lock:
            turn = self._turns.get(trace_id)
        if turn is not None:
            return turn
        if self._path is None:
            return None
        loaded = self._load_turn(trace_id)
        if loaded is not None:
            with self._lock:
                self._turns[trace_id] = loaded
        return loaded

    def update_turn_status(self, trace_id: str, *, status: TurnStatus) -> None:
        if not trace_id:
            return
        with self._lock:
            turn = self._turns.get(trace_id)
            if turn is None:
                return
            turn.status = status
            self._save_turn(turn)

    def end_turn(self, trace_id: str, *, status: TurnStatus = "completed") -> None:
        if not trace_id:
            return
        with self._lock:
            turn = self._turns.get(trace_id)
            if turn is not None:
                turn.status = status
                self._save_turn(turn)

    def clear_turn(self, trace_id: str) -> None:
        if not trace_id:
            return
        with self._lock:
            self._turns.pop(trace_id, None)
        if self._path is not None:
            document = self._load_document()
            turns = document.get("turns", {})
            pauses = document.get("pauses", {})
            if isinstance(turns, dict):
                turns.pop(trace_id, None)
            if isinstance(pauses, dict):
                pauses.pop(trace_id, None)
            self._write_document({"turns": turns, "pauses": pauses})

    def save_pause(self, trace_id: str, *, kind: PauseKind, data: dict[str, Any]) -> None:
        """Merge one pause kind into the per-trace multi-kind bundle (does not wipe others)."""
        if not trace_id or self._path is None:
            return
        with self._lock:
            document = self._load_document()
            pauses = document.get("pauses", {})
            if not isinstance(pauses, dict):
                pauses = {}
            entry = _normalize_pause_entry(pauses.get(trace_id))
            entry[kind] = data
            pauses[trace_id] = _pause_entry_to_disk(entry)
            self._write_document({"turns": document.get("turns", {}), "pauses": pauses})

    def load_pauses(self, trace_id: str) -> dict[PauseKind, dict[str, Any]]:
        """Return all pause kinds stored for a trace (empty dict if none)."""
        if not trace_id or self._path is None:
            return {}
        raw = self._load_document().get("pauses", {}).get(trace_id)
        return _normalize_pause_entry(raw)

    def clear_pause(self, trace_id: str) -> None:
        if not trace_id or self._path is None:
            return
        with self._lock:
            document = self._load_document()
            pauses = document.get("pauses", {})
            if isinstance(pauses, dict):
                pauses.pop(trace_id, None)
            self._write_document({"turns": document.get("turns", {}), "pauses": pauses})

    def prune_stale(
        self,
        *,
        max_age_hours: float = 72,
        max_turns: int = 200,
    ) -> int:
        """Drop old completed turns; never drop traces that still have pauses.

        Returns number of turns removed from persistence.
        """
        if self._path is None:
            return 0
        cutoff = datetime.now(UTC).timestamp() - max_age_hours * 3600
        removed = 0
        with self._lock:
            document = self._load_document()
            turns_raw = document.get("turns", {})
            pauses_raw = document.get("pauses", {})
            if not isinstance(turns_raw, dict):
                turns_raw = {}
            if not isinstance(pauses_raw, dict):
                pauses_raw = {}

            survivors: list[tuple[str, float, dict[str, Any], bool]] = []
            for trace_id, raw in turns_raw.items():
                if not isinstance(raw, dict):
                    continue
                tid = str(trace_id)
                has_pause = tid in pauses_raw
                status = str(raw.get("status") or "")
                started = str(raw.get("started_at") or "")
                try:
                    started_ts = datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    started_ts = datetime.now(UTC).timestamp()
                if (
                    not has_pause
                    and status in {"completed", "failed", "cancelled"}
                    and started_ts < cutoff
                ):
                    removed += 1
                    self._turns.pop(tid, None)
                    continue
                survivors.append((tid, started_ts, raw, has_pause))

            survivors.sort(key=lambda item: (item[3], item[1]), reverse=True)
            final_turns: dict[str, Any] = {}
            for tid, _ts, raw, has_pause in survivors:
                if len(final_turns) >= max_turns and not has_pause:
                    removed += 1
                    self._turns.pop(tid, None)
                    continue
                final_turns[tid] = raw

            # Always retain pause-only traces (no turn row yet / restart mid-confirm).
            pauses_kept: dict[str, Any] = {}
            for tid, payload in pauses_raw.items():
                pauses_kept[tid] = payload
                if tid not in final_turns:
                    final_turns[tid] = {
                        "turn_id": tid,
                        "trace_id": tid,
                        "thread_id": "",
                        "user_message": "",
                        "parent_turn_id": "",
                        "child_id": "",
                        "status": "paused",
                        "started_at": datetime.now(UTC).isoformat(),
                        "item_seq": 0,
                    }
            self._write_document({"turns": final_turns, "pauses": pauses_kept})
        return removed

    def _load_document(self) -> dict[str, Any]:
        if self._path is None or not self._path.exists():
            return {"turns": {}, "pauses": {}}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"turns": {}, "pauses": {}}
        if not isinstance(payload, dict):
            return {"turns": {}, "pauses": {}}
        turns = payload.get("turns")
        pauses = payload.get("pauses")
        return {
            "turns": turns if isinstance(turns, dict) else {},
            "pauses": pauses if isinstance(pauses, dict) else {},
        }

    def _write_document(self, document: dict[str, Any]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "turns": document.get("turns", {}),
            "pauses": document.get("pauses", {}),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(self._path)

    def _load_turns(self) -> dict[str, TurnContext]:
        turns: dict[str, TurnContext] = {}
        for trace_id, raw in self._load_document()["turns"].items():
            if not isinstance(raw, dict):
                continue
            turn = _turn_from_dict(raw)
            if turn is not None:
                turns[str(trace_id)] = turn
        return turns

    def _load_turn(self, trace_id: str) -> TurnContext | None:
        raw = self._load_document()["turns"].get(trace_id)
        if not isinstance(raw, dict):
            return None
        return _turn_from_dict(raw)

    def _save_turn(self, turn: TurnContext) -> None:
        if self._path is None:
            return
        document = self._load_document()
        turns = document.get("turns", {})
        if not isinstance(turns, dict):
            turns = {}
        turns[turn.trace_id] = _turn_to_dict(turn)
        self._write_document({"turns": turns, "pauses": document.get("pauses", {})})
