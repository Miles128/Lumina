"""Browser tools via agent-browser CLI (P1 harness integration)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_CLI = "agent-browser"
_DEFAULT_TIMEOUT = 90.0
_SESSION_PREFIX = "lumina-"


def agent_browser_available() -> bool:
    return shutil.which(_CLI) is not None


def lumina_browser_session(chat_session_id: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]", "", chat_session_id)[:48] or "default"
    return f"{_SESSION_PREFIX}{token}"


def run_agent_browser(
    args: list[str],
    *,
    session: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """Run agent-browser with an isolated session. Returns (success, output)."""
    if not agent_browser_available():
        return False, (
            "Error: 未找到 agent-browser CLI。请安装："
            "npm i -g agent-browser && agent-browser install"
        )
    command = [_CLI, *args, "--session", session]
    env = os.environ.copy()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"Error: agent-browser 超时（>{int(timeout)}s）"
    except OSError as exc:
        return False, f"Error: 无法启动 agent-browser: {exc}"

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    output = stdout or stderr or "(empty)"
    if completed.returncode != 0:
        if stderr and stderr not in output:
            output = f"{output}\n{stderr}".strip()
        if not output.lower().startswith("error"):
            output = f"Error: {output}"
        return False, output
    return True, output


class _BrowserSessionTool(Tool):
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def __init__(self, session: str) -> None:
        self._session = session

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"{self.name} (session={self._session})"


class BrowserOpenTool(_BrowserSessionTool):
    name = "browser_open"
    description = (
        "Open a URL in a real browser (agent-browser). "
        "Use for JS-rendered pages, logins, or when web_fetch returns empty shell."
    )

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) URL to open"},
            },
            "required": ["url"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"打开网页 {arguments.get('url', '')}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        url = str(arguments.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult.failure(
                "Error: url must start with http:// or https://",
                error_type="validation",
                retryable=False,
            )
        ok, output = run_agent_browser(["open", url], session=self._session)
        return output if ok else output


class BrowserSnapshotTool(_BrowserSessionTool):
    name = "browser_snapshot"
    description = (
        "Snapshot the current page accessibility tree with @refs (e1, e2, …). "
        "Call after browser_open before click/fill."
    )

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "interactive_only": {
                    "type": "boolean",
                    "description": "Only interactive elements (default true)",
                },
                "include_urls": {
                    "type": "boolean",
                    "description": "Include link URLs (default true)",
                },
                "depth": {
                    "type": "integer",
                    "description": "Max tree depth (default 6)",
                },
            },
            "required": [],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "获取浏览器页面快照（accessibility tree）"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        args = ["snapshot", "-i", "-c", "--depth", str(int(arguments.get("depth", 6)))]
        if arguments.get("include_urls", True):
            args.append("--urls")
        ok, output = run_agent_browser(args, session=self._session, timeout=120.0)
        if ok and len(output) > 8000:
            return output[:8000] + "\n…(truncated)"
        return output


class BrowserScreenshotTool(_BrowserSessionTool):
    name = "browser_screenshot"
    description = (
        "Take a screenshot of the current browser page. "
        "Use after browser_open; supports full-page and annotated element labels."
    )

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional output path (.png/.jpeg)"},
                "full_page": {"type": "boolean", "description": "Capture full scrollable page"},
                "annotate": {
                    "type": "boolean",
                    "description": "Overlay numbered labels on interactive elements",
                },
            },
            "required": [],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "浏览器截图"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        args = ["screenshot"]
        path = str(arguments.get("path", "")).strip()
        if path:
            args.append(path)
        if arguments.get("full_page"):
            args.append("--full")
        if arguments.get("annotate"):
            args.append("--annotate")
        ok, output = run_agent_browser(args, session=self._session, timeout=120.0)
        return output if ok else output


class BrowserClickTool(_BrowserSessionTool):
    name = "browser_click"
    description = "Click an element by @ref from browser_snapshot or CSS selector."

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Element @ref (e.g. @e2) or CSS selector",
                },
            },
            "required": ["target"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"点击 {arguments.get('target', '')}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        target = str(arguments.get("target", "")).strip()
        if not target:
            return ToolResult.failure(
                "Error: target is required",
                error_type="validation",
                retryable=False,
            )
        ok, output = run_agent_browser(["click", target], session=self._session)
        return output


class BrowserFillTool(_BrowserSessionTool):
    name = "browser_fill"
    description = "Clear and fill an input by @ref or CSS selector."

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "@ref or CSS selector"},
                "text": {"type": "string", "description": "Text to fill"},
            },
            "required": ["target", "text"],
        }

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return f"填写 {arguments.get('target', '')}"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        target = str(arguments.get("target", "")).strip()
        text = str(arguments.get("text", ""))
        if not target:
            return ToolResult.failure(
                "Error: target is required",
                error_type="validation",
                retryable=False,
            )
        ok, output = run_agent_browser(["fill", target, text], session=self._session)
        return output


class BrowserCloseTool(_BrowserSessionTool):
    name = "browser_close"
    description = "Close the browser session when done with browser tools."

    def _parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        return "关闭浏览器会话"

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str | ToolResult:
        ok, output = run_agent_browser(["close"], session=self._session)
        return output if ok else output


def build_browser_tools(chat_session_id: str) -> list[Tool]:
    if not agent_browser_available():
        return []
    session = lumina_browser_session(chat_session_id)
    return [
        BrowserOpenTool(session),
        BrowserSnapshotTool(session),
        BrowserScreenshotTool(session),
        BrowserClickTool(session),
        BrowserFillTool(session),
        BrowserCloseTool(session),
    ]
