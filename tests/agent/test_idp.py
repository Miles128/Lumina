"""Internal Delegation Protocol (IDP) unit tests."""

from __future__ import annotations

import pytest

from secretary.agent.idp import (
    IdpStore,
    assert_channel_allowed,
    build_envelope,
    get_idp_store,
    protocol_constants,
    resolve_conflict_policy,
)


def test_protocol_constants_surface() -> None:
    consts = protocol_constants()
    assert consts["protocol"] == "idp/v1"
    assert consts["channel"] == "parent_child_only"
    assert consts["peer_channel_allowed"] is False
    assert "spawn" in consts["lifecycle"]
    assert "parent_synthesize" in consts["conflict_policies"]
    assert consts["topology"]["max_spawn_depth"] == 1


def test_build_envelope_and_conflict_policies() -> None:
    env = build_envelope(
        run_id="r1",
        goal="find auth",
        archetype="explore",
        tool_names={"read", "grep"},
        max_rounds=8,
        parallel_batch=True,
    )
    assert env.conflict_policy == "parent_synthesize"
    assert env.return_schema == "summary_only"
    assert env.channel == "parent_child_only"
    assert env.tool_scope == ("grep", "read")
    assert resolve_conflict_policy(parallel_batch=False, archetype="verify") == "verify_once"
    assert resolve_conflict_policy(parallel_batch=False, archetype="worker") == "parent_synthesize"


def test_peer_channel_forbidden() -> None:
    assert_channel_allowed(from_run_id="parent", to_run_id="child", parent_run_id="parent")
    with pytest.raises(PermissionError, match="peer"):
        assert_channel_allowed(from_run_id="a", to_run_id="b", parent_run_id="parent")


def test_store_lifecycle_and_snapshot() -> None:
    store = IdpStore()
    env = build_envelope(
        run_id="abc",
        goal="g",
        archetype="explore",
        tool_names={"read"},
        max_rounds=4,
    )
    store.begin("trace-1", env)
    store.transition("trace-1", "abc", "running")
    store.transition("trace-1", "abc", "result", summary_preview="done", success=True)
    view = store.snapshot("trace-1")
    assert view.protocol == "idp/v1"
    assert len(view.delegations) == 1
    rec = view.delegations[0]
    assert rec.state == "result"
    assert rec.success is True
    assert [h.state for h in rec.history] == ["spawn", "running", "result"]
    payload = view.to_dict()
    assert payload["delegations"][0]["envelope"]["run_id"] == "abc"


def test_transition_falls_back_by_run_id() -> None:
    store = IdpStore()
    env = build_envelope(
        run_id="xyz",
        goal="g",
        archetype="worker",
        tool_names={"write"},
        max_rounds=6,
    )
    store.begin("t-a", env)
    # Empty trace_id should still find the run
    rec = store.transition("", "xyz", "pause_confirm", detail="shell")
    assert rec is not None
    assert rec.state == "pause_confirm"


def test_global_store_singleton() -> None:
    assert get_idp_store() is get_idp_store()
