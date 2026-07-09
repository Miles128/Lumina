"""Debug script: capture console logs from chat.js debug logging."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8766/"


def main() -> None:
    logs: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: logs.append(f"[pageerror] {err.message}\n{err.stack}"))

        def fulfill_chat(route, request):
            if request.method != "POST":
                route.continue_()
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "reply": "你好，我是灵犀。",
                    "profile_excerpt": "",
                    "used_tools": [],
                    "total_steps": 1,
                    "route": "",
                    "needs_confirmation": False,
                    "confirmation_description": "",
                    "confirmation_action_id": "",
                    "confirmation_risk_level": "",
                    "confirmation_kind": "",
                    "allow_permanent_read": False,
                    "allow_session_write": False,
                    "grounding_verified": True,
                    "grounding_note": "",
                    "files_read": [],
                    "usage_prompt_tokens": 1,
                    "usage_completion_tokens": 2,
                    "usage_total_tokens": 3,
                }),
            )

        page.route("**/api/chat", fulfill_chat)
        page.goto(BASE_URL, wait_until="networkidle")
        page.locator("#chat-input").wait_for(state="visible", timeout=10_000)

        page.locator("#chat-input").fill("你好")
        page.locator("#btn-send").click()
        page.wait_for_timeout(3000)

        result = page.evaluate("""() => ({
            botCount: document.querySelectorAll('.message.bot').length,
            userCount: document.querySelectorAll('.message.user').length,
            welcomeHidden: document.getElementById('welcome').classList.contains('hidden'),
        })""")
        print(f"result: {json.dumps(result, indent=2)}")

        print("=== LOGS ===")
        for line in logs:
            print(line)

        browser.close()


if __name__ == "__main__":
    main()
