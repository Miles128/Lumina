"""BackgroundReviewService after profile merge into MEMORY.md."""

from unittest.mock import MagicMock

from secretary.services.background_review import BackgroundReviewService, ReviewDecision


def test_target_user_appends_memory_md() -> None:
    """target=user is remapped to MEMORY.md append."""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="add", target="user", text="Name: Alex", old_text="", reason="user said name"
    )
    svc.apply_decision_for_tests(decision)

    memory.mutate_memory.assert_not_called()
    memory.append_memory_md.assert_called_once_with("Name: Alex")
    profile.append_chat_fact.assert_not_called()


def test_target_memory_calls_mutate_memory_only() -> None:
    """target=memory 时：只调 mutate_memory。"""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="add", target="memory", text="Uses macOS", old_text="", reason="env fact"
    )
    svc.apply_decision_for_tests(decision)

    memory.mutate_memory.assert_called_once_with(
        "add", "memory", text="Uses macOS", old_text=""
    )
    memory.append_memory_md.assert_not_called()


def test_target_user_replace_also_appends_memory() -> None:
    """target=user + action=replace also appends to MEMORY.md."""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="replace", target="user", text="Name: Bob", old_text="Name: Alex", reason="rename"
    )
    svc.apply_decision_for_tests(decision)

    memory.mutate_memory.assert_not_called()
    memory.append_memory_md.assert_called_once_with("Name: Bob")
