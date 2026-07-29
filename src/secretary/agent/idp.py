"""Internal Delegation Protocol (IDP) — typed harness for parent→child spawn.

Formalizes existing shallow-tree delegation (depth=1, summary return, no peer
channel) so collaboration is a protocol, not just PRD prose.

See docs/superpowers/specs/2026-07-27-idp-design.md.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Final, Literal

ChannelPolicy = Literal["parent_child_only"]
ReturnSchema = Literal["summary_only"]
ConflictPolicy = Literal["parent_synthesize", "ask_user", "verify_once"]
LifecycleState = Literal[
    "spawn",
    "running",
    "pause_confirm",
    "pause_ask",
    "resume",
    "result",
    "fail",
    "cancel",
]

PROTOCOL_ID: Final = "idp/v1"
CHANNEL: Final[ChannelPolicy] = "parent_child_only"
RETURN_SCHEMA: Final[ReturnSchema] = "summary_only"
# Peer messaging is a protocol violation (not merely a product preference).
PEER_CHANNEL_ALLOWED: Final = False

LIFECYCLE_STATES: Final[tuple[LifecycleState, ...]] = (
    "spawn",
    "running",
    "pause_confirm",
    "pause_ask",
    "resume",
    "result",
    "fail",
    "cancel",
)
CONFLICT_POLICIES: Final[tuple[ConflictPolicy, ...]] = (
    "parent_synthesize",
    "ask_user",
    "verify_once",
)

# Truncation limits for observation / SSE payloads (single source of truth).
GOAL_PREVIEW_CHARS: Final = 500
CONTEXT_PREVIEW_CHARS: Final = 500
SUMMARY_PREVIEW_CHARS: Final = 400
TRANSITION_DETAIL_CHARS: Final = 300

# Defaults mirror subagent.policy (imported lazily to avoid package cycle).
_DEFAULT_MAX_SPAWN_DEPTH = 1
_DEFAULT_MAX_SPAWNS_PER_TURN = 3
_DEFAULT_MAX_PARALLEL_EXPLORE = 3
_EMPTY_TRACE_KEY: Final = "_"


def _topology() -> tuple[int, int, int]:
    """Return (max_depth, max_spawns_per_turn, max_parallel_explore)."""
    try:
        from secretary.agent.subagent.policy import (
            MAX_PARALLEL_EXPLORE,
            MAX_SPAWN_DEPTH,
            MAX_SPAWNS_PER_TURN,
        )

        return MAX_SPAWN_DEPTH, MAX_SPAWNS_PER_TURN, MAX_PARALLEL_EXPLORE
    except Exception:
        return (
            _DEFAULT_MAX_SPAWN_DEPTH,
            _DEFAULT_MAX_SPAWNS_PER_TURN,
            _DEFAULT_MAX_PARALLEL_EXPLORE,
        )


@dataclass(frozen=True)
class DelegationBudget:
    """Resource envelope for one delegated run."""

    max_rounds: int
    max_depth: int = _DEFAULT_MAX_SPAWN_DEPTH
    token_budget: int | None = None  # optional soft cap; None = harness default
    timeout_sec: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_rounds": self.max_rounds,
            "max_depth": self.max_depth,
            "token_budget": self.token_budget,
            "timeout_sec": self.timeout_sec,
        }


@dataclass(frozen=True)
class DelegationEnvelope:
    """Typed spawn contract (goal + permissions + budget + return shape)."""

    run_id: str
    goal: str
    archetype: str
    tool_scope: tuple[str, ...]
    budget: DelegationBudget
    return_schema: ReturnSchema = RETURN_SCHEMA
    channel: ChannelPolicy = CHANNEL
    conflict_policy: ConflictPolicy = "parent_synthesize"
    parent_run_id: str = ""
    depth: int = 0
    batch_id: str = ""  # shared id when goals[] parallel explore
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "archetype": self.archetype,
            "tool_scope": list(self.tool_scope),
            "budget": self.budget.to_dict(),
            "return_schema": self.return_schema,
            "channel": self.channel,
            "conflict_policy": self.conflict_policy,
            "parent_run_id": self.parent_run_id,
            "depth": self.depth,
            "batch_id": self.batch_id,
            "context": self.context[:CONTEXT_PREVIEW_CHARS] if self.context else "",
            "peer_channel_allowed": PEER_CHANNEL_ALLOWED,
        }


@dataclass
class LifecycleTransition:
    state: LifecycleState
    at: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "at": self.at, "detail": self.detail}


@dataclass
class DelegationRecord:
    """Live observation record for one envelope."""

    envelope: DelegationEnvelope
    state: LifecycleState
    history: list[LifecycleTransition] = field(default_factory=list)
    summary_preview: str = ""
    success: bool | None = None

    def transition(self, state: LifecycleState, *, detail: str = "") -> None:
        self.state = state
        self.history.append(
            LifecycleTransition(
                state=state,
                at=time.time(),
                detail=detail[:TRANSITION_DETAIL_CHARS],
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope": self.envelope.to_dict(),
            "state": self.state,
            "history": [h.to_dict() for h in self.history],
            "summary_preview": self.summary_preview[:SUMMARY_PREVIEW_CHARS],
            "success": self.success,
        }


@dataclass
class IdpTraceView:
    """Read-only snapshot for a turn/trace."""

    trace_id: str
    protocol: str = PROTOCOL_ID
    channel: ChannelPolicy = CHANNEL
    peer_channel_allowed: bool = PEER_CHANNEL_ALLOWED
    max_spawn_depth: int = _DEFAULT_MAX_SPAWN_DEPTH
    max_spawns_per_turn: int = _DEFAULT_MAX_SPAWNS_PER_TURN
    max_parallel_explore: int = _DEFAULT_MAX_PARALLEL_EXPLORE
    default_conflict_policy: ConflictPolicy = "parent_synthesize"
    delegations: list[DelegationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        depth, spawns, parallel = _topology()
        return {
            "protocol": self.protocol,
            "trace_id": self.trace_id,
            "channel": self.channel,
            "peer_channel_allowed": self.peer_channel_allowed,
            "topology": {
                "max_spawn_depth": depth,
                "max_spawns_per_turn": spawns,
                "max_parallel_explore": parallel,
            },
            "default_conflict_policy": self.default_conflict_policy,
            "delegations": [d.to_dict() for d in self.delegations],
        }


class IdpStore:
    """In-memory IDP observation store (per-process, keyed by trace_id)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_trace: dict[str, dict[str, DelegationRecord]] = {}

    def begin(
        self,
        trace_id: str,
        envelope: DelegationEnvelope,
    ) -> DelegationRecord:
        if not trace_id:
            # Still track under empty key for unit tests without a chat turn.
            trace_id = _EMPTY_TRACE_KEY
        record = DelegationRecord(envelope=envelope, state="spawn")
        record.transition("spawn")
        with self._lock:
            bucket = self._by_trace.setdefault(trace_id, {})
            bucket[envelope.run_id] = record
        return record

    def transition(
        self,
        trace_id: str,
        run_id: str,
        state: LifecycleState,
        *,
        detail: str = "",
        summary_preview: str = "",
        success: bool | None = None,
    ) -> DelegationRecord | None:
        key = trace_id or _EMPTY_TRACE_KEY
        with self._lock:
            record = self._by_trace.get(key, {}).get(run_id)
            if record is None:
                # Resume paths may lack trace_id; fall back to run_id scan.
                for bucket in self._by_trace.values():
                    if run_id in bucket:
                        record = bucket[run_id]
                        break
            if record is None:
                return None
            record.transition(state, detail=detail)
            if summary_preview:
                record.summary_preview = summary_preview[:SUMMARY_PREVIEW_CHARS]
            if success is not None:
                record.success = success
            return record

    def snapshot(self, trace_id: str) -> IdpTraceView:
        key = trace_id or _EMPTY_TRACE_KEY
        with self._lock:
            records = list(self._by_trace.get(key, {}).values())
        # Stable order: spawn time via first history entry
        records.sort(key=lambda r: r.history[0].at if r.history else 0.0)
        return IdpTraceView(trace_id=trace_id, delegations=records)

    def clear(self, trace_id: str) -> None:
        with self._lock:
            self._by_trace.pop(trace_id or _EMPTY_TRACE_KEY, None)


_GLOBAL_STORE = IdpStore()


def get_idp_store() -> IdpStore:
    return _GLOBAL_STORE


# Archetype-specific conflict defaults (overridden by parallel_batch).
_ARCHETYPE_CONFLICT: Final[dict[str, ConflictPolicy]] = {
    "verify": "verify_once",
}


def resolve_conflict_policy(
    *,
    parallel_batch: bool,
    archetype: str,
) -> ConflictPolicy:
    """Map runtime shape onto a protocol conflict option.

    Parallel explore → parent synthesizes (current behavior).
    Single verify → verify_once (the verify *is* the conflict tool).
    Otherwise default parent_synthesize; ask_user is chosen by parent via tool.
    """
    if parallel_batch:
        return "parent_synthesize"
    return _ARCHETYPE_CONFLICT.get(archetype, "parent_synthesize")


def build_envelope(
    *,
    run_id: str,
    goal: str,
    archetype: str,
    tool_names: frozenset[str] | set[str] | tuple[str, ...],
    max_rounds: int,
    depth: int = 0,
    parent_run_id: str = "",
    batch_id: str = "",
    context: str = "",
    parallel_batch: bool = False,
    token_budget: int | None = None,
    timeout_sec: int | None = None,
) -> DelegationEnvelope:
    scope = tuple(sorted(tool_names))
    max_depth, _, _ = _topology()
    return DelegationEnvelope(
        run_id=run_id,
        goal=goal[:GOAL_PREVIEW_CHARS],
        archetype=archetype,
        tool_scope=scope,
        budget=DelegationBudget(
            max_rounds=max_rounds,
            max_depth=max_depth,
            token_budget=token_budget,
            timeout_sec=timeout_sec,
        ),
        conflict_policy=resolve_conflict_policy(
            parallel_batch=parallel_batch,
            archetype=archetype,
        ),
        parent_run_id=parent_run_id,
        depth=depth,
        batch_id=batch_id,
        context=context[:CONTEXT_PREVIEW_CHARS],
    )


def assert_channel_allowed(*, from_run_id: str, to_run_id: str, parent_run_id: str) -> None:
    """Raise if a peer (non parent↔child) message is attempted."""
    if PEER_CHANNEL_ALLOWED:
        return
    # Allowed: parent→child (parent_run_id empty or equals from) or child→parent
    if not parent_run_id:
        return
    if from_run_id == parent_run_id or to_run_id == parent_run_id:
        return
    raise PermissionError(
        f"IDP channel violation: peer messaging forbidden "
        f"(from={from_run_id} to={to_run_id}; channel=parent_child_only)"
    )


def idp_progress_detail(record: DelegationRecord) -> str:
    """Compact JSON-ish detail for SSE (kept short for UI)."""
    env = record.envelope
    return (
        f"idp state={record.state} arch={env.archetype} "
        f"conflict={env.conflict_policy} depth={env.depth} "
        f"tools={len(env.tool_scope)} rounds≤{env.budget.max_rounds}"
    )


def protocol_constants() -> dict[str, Any]:
    """Static protocol surface for docs / settings / interview demos."""
    from secretary.agent.write_gate import DISPLAY_NAMES

    depth, spawns, parallel = _topology()
    return {
        "protocol": PROTOCOL_ID,
        "channel": CHANNEL,
        "peer_channel_allowed": PEER_CHANNEL_ALLOWED,
        "return_schema": RETURN_SCHEMA,
        "lifecycle": list(LIFECYCLE_STATES),
        "conflict_policies": list(CONFLICT_POLICIES),
        "topology": {
            "max_spawn_depth": depth,
            "max_spawns_per_turn": spawns,
            "max_parallel_explore": parallel,
        },
        "role_display_names": dict(DISPLAY_NAMES),
        "envelope_fields": [
            "goal",
            "archetype",
            "tool_scope",
            "budget",
            "return_schema",
            "channel",
            "conflict_policy",
        ],
    }


def record_to_public_dict(record: DelegationRecord) -> dict[str, Any]:
    """Alias for tests / API."""
    return record.to_dict()


def idp_sse_payload(record: DelegationRecord) -> dict[str, Any]:
    """Observation dict for SSE — includes shared UI metadata once per event."""
    from secretary.agent.write_gate import DISPLAY_NAMES

    depth, _, _ = _topology()
    payload = record.to_dict()
    payload["role_display_names"] = dict(DISPLAY_NAMES)
    payload["topology"] = {"max_spawn_depth": depth}
    return payload
