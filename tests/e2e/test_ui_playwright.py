"""Playwright UI E2E — chat page served from FastAPI / (same as Electron)."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def _open_settings(page: Page) -> None:
    page.locator("#btn-topbar-menu").click()
    page.locator("#btn-platforms").click()
    expect(page.locator("#settings-panel")).to_be_visible(timeout=10_000)


def test_ui_chat_shell_loads(page: Page) -> None:
    page.goto("/")
    expect(page.locator("#chat-input")).to_be_visible()
    expect(page.locator("#btn-send")).to_be_visible()
    expect(page.locator("#welcome")).to_be_visible()
    expect(page.locator("#messages")).to_be_attached()
    expect(page.locator("#btn-pause")).to_be_hidden()


def test_ui_identity_reply_in_thread(page: Page) -> None:
    page.goto("/")
    page.locator("#chat-input").fill("你是谁")
    page.locator("#btn-send").click()
    bot = page.locator(".message.bot").last
    expect(bot).to_be_visible(timeout=15_000)
    expect(bot).to_contain_text(re.compile(r"灵犀|Lumina"))


def test_ui_weread_empty_shows_sync_hint(page: Page) -> None:
    page.goto("/")
    page.locator("#chat-input").fill("我微信读书最近在读什么")
    page.locator("#btn-send").click()
    bot = page.locator(".message.bot").last
    expect(bot).to_be_visible(timeout=15_000)
    expect(bot).to_contain_text("同步")


def test_ui_greeting_with_mocked_llm(page: Page) -> None:
    def fulfill_chat(route, request) -> None:
        if request.method != "POST":
            route.continue_()
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"reply":"你好，我是灵犀。",'
                '"profile_excerpt":"","used_tools":[],"total_steps":1,'
                '"route":"","needs_confirmation":false,'
                '"confirmation_description":"","confirmation_action_id":"",'
                '"confirmation_risk_level":"","confirmation_kind":"",'
                '"allow_permanent_read":false,"allow_session_write":false,'
                '"grounding_verified":true,"grounding_note":"","files_read":[],'
                '"usage_prompt_tokens":1,"usage_completion_tokens":2,"usage_total_tokens":3}'
            ),
        )

    page.route("**/api/chat", fulfill_chat)
    page.goto("/")
    page.locator("#chat-input").fill("你好")
    page.locator("#btn-send").click()
    bot = page.locator(".message.bot").last
    expect(bot).to_be_visible(timeout=10_000)
    expect(bot).to_contain_text("你好")


def test_ui_settings_shibei_pane(page: Page) -> None:
    page.goto("/")
    _open_settings(page)
    page.locator("#settings-nav").get_by_text("Shibei", exact=False).click()
    expect(page.locator("#shibei-install-path")).to_be_visible(timeout=10_000)
    expect(page.locator("#shibei-enabled")).to_be_visible()


def test_ui_sync_button_triggers_api(page: Page) -> None:
    sync_hits: list[str] = []

    def track_sync(route, request) -> None:
        sync_hits.append(request.method)
        route.fulfill(
            status=200,
            content_type="application/json",
            body="[]",
        )

    page.route("**/api/sync", track_sync)
    page.goto("/")
    page.locator("#btn-topbar-menu").click()
    page.locator("#btn-sync").click()
    page.wait_for_timeout(800)
    assert sync_hits, "expected POST /api/sync from sync button"
