"""Internal Delegation Protocol (IDP) unit tests."""

from __future__ import annotations

import pytest

from secretary.agent.idp import (
    CONFLICT_POLICIES,
    GOAL_PREVIEW_CHARS,
    LIFECYCLE_STATES,
    PROTOCOL_ID,
    IdpStore,
    assert_channel_allowed,
    build_envelope,
    get_idp_store,
    idp_progress_detail,
    idp_sse_payload,
    protocol_constants,
    resolve_conflict_policy,
)


def test_protocol_constants_surface() -> None:
    consts = protocol_constants()
    assert consts["protocol"] == PROTOCOL_ID
    assert consts["channel"] == "parent_child_only"
    assert consts["peer_channel_allowed"] is False
    assert list(consts["lifecycle"]) == list(LIFECYCLE_STATES)
    assert list(consts["conflict_policies"]) == list(CONFLICT_POLICIES)
    assert consts["topology"]["max_spawn_depth"] == 1
    assert consts["role_display_names"]["root"] == "项目主管"
    assert consts["role_display_names"]["pro"] == "方案主张"


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
    assert resolve_conflict_policy(parallel_batch=True, archetype="verify") == "parent_synthesize"


def test_build_envelope_truncates_goal_and_context() -> None:
    env = build_envelope(
        run_id="long",
        goal="g" * (GOAL_PREVIEW_CHARS + 50),
        archetype="explore",
        tool_names={"read"},
        max_rounds=2,
        context="c" * (GOAL_PREVIEW_CHARS + 10),
    )
    assert len(env.goal) == GOAL_PREVIEW_CHARS
    assert len(env.context) == GOAL_PREVIEW_CHARS


def test_peer_channel_forbidden() -> None:
    assert_channel_allowed(from_run_id="parent", to_run_id="child", parent_run_id="parent")
    assert_channel_allowed(from_run_id="child", to_run_id="parent", parent_run_id="parent")
    assert_channel_allowed(from_run_id="a", to_run_id="b", parent_run_id="")
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
    assert view.protocol == PROTOCOL_ID
    assert len(view.delegations) == 1
    rec = view.delegations[0]
    assert rec.state == "result"
    assert rec.success is True
    assert [h.state for h in rec.history] == ["spawn", "running", "result"]
    payload = view.to_dict()
    assert payload["delegations"][0]["envelope"]["run_id"] == "abc"
    detail = idp_progress_detail(rec)
    assert "idp state=result" in detail
    assert "arch=explore" in detail


def test_transition_unknown_run_returns_none() -> None:
    store = IdpStore()
    assert store.transition("missing", "nope", "running") is None


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


def test_store_clear() -> None:
    store = IdpStore()
    env = build_envelope(
        run_id="c1",
        goal="g",
        archetype="explore",
        tool_names={"read"},
        max_rounds=2,
    )
    store.begin("t-clear", env)
    assert len(store.snapshot("t-clear").delegations) == 1
    store.clear("t-clear")
    assert store.snapshot("t-clear").delegations == []


def test_snapshot_orders_by_spawn_time() -> None:
    store = IdpStore()
    for run_id in ("second", "first"):
        store.begin(
            "ord",
            build_envelope(
                run_id=run_id,
                goal=run_id,
                archetype="explore",
                tool_names={"read"},
                max_rounds=1,
            ),
        )
    ids = [d.envelope.run_id for d in store.snapshot("ord").delegations]
    assert ids == ["second", "first"]


def test_global_store_singleton() -> None:
    assert get_idp_store() is get_idp_store()


def test_idp_sse_payload_includes_shared_ui_meta() -> None:
    store = IdpStore()
    env = build_envelope(
        run_id="sse1",
        goal="g",
        archetype="worker",
        tool_names={"write"},
        max_rounds=2,
    )
    rec = store.begin("t-sse", env)
    payload = idp_sse_payload(rec)
    assert payload["envelope"]["run_id"] == "sse1"
    assert payload["role_display_names"]["worker"] == "执行者"
    assert "max_spawn_depth" in payload["topology"]
