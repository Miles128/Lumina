"""BackgroundReviewService 在 USER.md 退役后的行为。"""

from unittest.mock import MagicMock

from secretary.services.background_review import BackgroundReviewService, ReviewDecision


def test_target_user_skips_mutate_memory_and_calls_profile_fact() -> None:
    """target=user 时：不调 mutate_memory（会抛错），只调 _sync_profile_fact。"""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="add", target="user", text="Name: Alex", old_text="", reason="user said name"
    )
    svc.apply_decision_for_tests(decision)

    # mutate_memory 不应被以 target=user 调用
    memory.mutate_memory.assert_not_called()
    # profile_service.append_chat_fact 应被调用一次，文本是 decision.text
    profile.append_chat_fact.assert_called_once_with("Name: Alex")


def test_target_memory_calls_mutate_memory_only() -> None:
    """target=memory 时：只调 mutate_memory，不调 profile。"""
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
    profile.append_chat_fact.assert_not_called()


def test_target_user_replace_action_also_syncs_profile() -> None:
    """target=user + action=replace 也应走 _sync_profile_fact。"""
    memory = MagicMock()
    profile = MagicMock()
    svc = BackgroundReviewService(memory, profile_service=profile)

    decision = ReviewDecision(
        action="replace", target="user", text="Name: Bob", old_text="Name: Alex", reason="rename"
    )
    svc.apply_decision_for_tests(decision)

    memory.mutate_memory.assert_not_called()
    profile.append_chat_fact.assert_called_once_with("Name: Bob")
