"""Tests for agent-browser tool wrappers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from secretary.agent.browser_routing import needs_browser_tools
from secretary.agent.browser_tools import (
    BrowserOpenTool,
    build_browser_tools,
    lumina_browser_session,
    run_agent_browser,
)


def test_needs_browser_tools_for_github() -> None:
    with patch("secretary.agent.browser_routing.agent_browser_available", return_value=True):
        assert needs_browser_tools("GitHub 最近涨星最快的项目")


def test_lumina_browser_session_sanitizes() -> None:
    assert lumina_browser_session("abc-123").startswith("lumina-")


def test_run_agent_browser_success() -> None:
    with patch("secretary.agent.browser_tools.agent_browser_available", return_value=True):
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "✓ Example Domain"
            run.return_value.stderr = ""
            ok, out = run_agent_browser(["open", "https://example.com"], session="lumina-test")
    assert ok
    assert "Example" in out


def test_browser_open_tool() -> None:
    tool = BrowserOpenTool("lumina-test")
    with patch("secretary.agent.browser_tools.run_agent_browser", return_value=(True, "ok")):
        assert tool.execute({"url": "https://example.com"}, __import__("pathlib").Path(".")) == "ok"


def test_needs_browser_tools_for_ask_research() -> None:
    from secretary.agent.agent_profile import AgentProfile

    with patch("secretary.agent.browser_routing.agent_browser_available", return_value=True):
        assert needs_browser_tools("帮我调研一下官网功能", profile=AgentProfile.ASK)


def test_browser_screenshot_tool() -> None:
    from secretary.agent.browser_tools import BrowserScreenshotTool

    tool = BrowserScreenshotTool("lumina-test")
    with patch("secretary.agent.browser_tools.run_agent_browser", return_value=(True, "saved.png")) as run:
        output = tool.execute({"full_page": True, "annotate": True}, Path("."))
    assert output == "saved.png"
    assert run.call_args.args[0] == ["screenshot", "--full", "--annotate"]


def test_build_browser_tools_empty_when_cli_missing() -> None:
    with patch("secretary.agent.browser_tools.agent_browser_available", return_value=False):
        assert build_browser_tools("sess") == []
