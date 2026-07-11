from secretary.agent.turn_cancel import begin_turn, end_turn, is_cancelled, request_cancel


def test_turn_cancel_registry_tracks_and_clears_trace_id() -> None:
    event = begin_turn("trace-1")

    assert event.is_set() is False
    assert is_cancelled("trace-1") is False

    assert request_cancel("trace-1") is True
    assert event.is_set() is True
    assert is_cancelled("trace-1") is True

    end_turn("trace-1")
    assert is_cancelled("trace-1") is False
    assert request_cancel("trace-1") is False


def test_begin_turn_replaces_stale_cancelled_event() -> None:
    stale = begin_turn("trace-2")
    assert request_cancel("trace-2") is True

    fresh = begin_turn("trace-2")

    assert stale.is_set() is True
    assert fresh.is_set() is False
    assert is_cancelled("trace-2") is False
