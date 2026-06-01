"""Tests for Lumina assistant identity routing."""

from secretary.agent.identity import LUMINA_IDENTITY_INTRO, get_identity_reply, is_identity_request
from secretary.agent.prompt_gate import GateAction, rule_route


def test_author_request_markers() -> None:
    from secretary.agent.identity import is_author_request

    assert is_author_request("你是谁写的")
    assert is_author_request("谁是你的作者")
    assert is_author_request("你的作者是谁")
    assert not is_author_request("你是谁")
    assert not is_author_request("做一下自我介绍")


def test_identity_not_author() -> None:
    from secretary.agent.identity import is_author_request, is_identity_request

    assert not is_identity_request("你是谁写的")
    assert is_author_request("你是谁写的")
    assert is_identity_request("你是谁")
    assert not is_identity_request("谁是你的作者")
    assert is_author_request("谁是你的作者")


def test_identity_request_markers() -> None:
    assert is_identity_request("你是谁")
    assert is_identity_request("介绍一下你自己")
    assert is_identity_request("请自我介绍")
    assert is_identity_request("做一下自我介绍")
    assert is_identity_request("来段自我介绍")
    assert is_identity_request("你介绍一下自己")
    assert is_identity_request("你是做什么的")
    assert is_identity_request("介绍一下灵犀")
    assert is_identity_request("让灵犀做自我介绍")
    assert is_identity_request("介绍一下")
    assert is_identity_request("再介绍一遍你自己")
    assert is_identity_request("你都能干什么")
    assert not is_identity_request("我是谁")
    assert not is_identity_request("帮我写一份自我介绍")
    assert not is_identity_request("我的自我介绍是什么样的")


def test_identity_repeat_after_intro() -> None:
    history = [
        {"role": "user", "content": "你是谁"},
        {"role": "assistant", "content": LUMINA_IDENTITY_INTRO},
    ]
    assert is_identity_request("再说一遍", history)
    assert is_identity_request("再来一次", history)


def test_identity_reply_is_fixed() -> None:
    assert get_identity_reply() == LUMINA_IDENTITY_INTRO


def test_rule_route_identity_variants() -> None:
    for message in ("你是谁", "做一下自我介绍", "来段自我介绍"):
        decision = rule_route(message)
        assert decision is not None
        assert decision.action == GateAction.IDENTITY


def test_rule_route_profile_not_identity() -> None:
    decision = rule_route("我是谁")
    assert decision is not None
    assert decision.action == GateAction.PROFILE


def test_identity_intro_mentions_real_stack() -> None:
    assert "Electron" in LUMINA_IDENTITY_INTRO
    assert "FastAPI" in LUMINA_IDENTITY_INTRO
    assert "轻巧灵动" in LUMINA_IDENTITY_INTRO
    assert "百炼" not in LUMINA_IDENTITY_INTRO
    assert "Apple Silicon" not in LUMINA_IDENTITY_INTRO
