"""Structured output cards (PRD F25) — marker protocol like ASK_USER_REQUEST."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from secretary.agent.tools.base import Tool

SUMMARY_CARD_PREFIX = "SUMMARY_CARD"
CODE_DIFF_CARD_PREFIX = "CODE_DIFF_CARD"
REFERENCE_CARD_PREFIX = "REFERENCE_CARD"

CARD_PREFIXES = (
    SUMMARY_CARD_PREFIX,
    CODE_DIFF_CARD_PREFIX,
    REFERENCE_CARD_PREFIX,
)


def is_structured_card_output(text: str) -> bool:
    cleaned = text.strip()
    return any(cleaned.startswith(prefix) for prefix in CARD_PREFIXES)


def is_loop_short_circuit_output(text: str) -> bool:
    """True when tool output should stop the loop and become the final reply."""
    from secretary.agent.p0_tools import is_user_input_request

    return is_user_input_request(text) or is_structured_card_output(text)


def format_card_reply(tool_output: str, *, thought: str = "") -> str:
    if is_structured_card_output(tool_output):
        return tool_output.strip()
    from secretary.agent.p0_tools import format_user_input_reply

    return format_user_input_reply(tool_output, thought=thought)


def _emit(prefix: str, payload: dict[str, Any]) -> str:
    return prefix + "\n" + json.dumps(payload, ensure_ascii=False)


class EmitCardTool(Tool):
    """Single tool for SUMMARY / CODE_DIFF / REFERENCE cards."""

    name = "emit_card"
    description = (
        "Emit a structured UI card and stop the turn. "
        "Kinds: summary (bullets), code_diff (unified diff), reference (links/citations). "
        "Use when the user should see a scannable card instead of plain prose."
    )
    needs_confirmation = False
    risk_level = "low"
    read_only = True

    def _parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["summary", "code_diff", "reference"],
                    "description": "Card kind.",
                },
                "title": {"type": "string", "description": "Card title."},
                "bullets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For summary: bullet points.",
                },
                "status": {
                    "type": "string",
                    "description": "For summary: ok | warn | error (optional).",
                },
                "path": {"type": "string", "description": "For code_diff: file path."},
                "language": {
                    "type": "string",
                    "description": "For code_diff: language hint (default diff).",
                },
                "diff": {"type": "string", "description": "For code_diff: unified diff text."},
                "references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                    },
                    "description": "For reference: citation list.",
                },
            },
            "required": ["kind"],
        }

    def execute(self, arguments: dict[str, Any], working_dir: Path) -> str:
        del working_dir
        kind = str(arguments.get("kind", "")).strip().lower()
        title = str(arguments.get("title", "")).strip()
        if kind == "summary":
            bullets = arguments.get("bullets") or []
            if not isinstance(bullets, list):
                bullets = [str(bullets)]
            payload = {
                "version": 1,
                "title": title or "Summary",
                "bullets": [str(item) for item in bullets],
                "status": str(arguments.get("status", "ok") or "ok"),
            }
            return _emit(SUMMARY_CARD_PREFIX, payload)
        if kind == "code_diff":
            payload = {
                "version": 1,
                "title": title or "Diff",
                "path": str(arguments.get("path", "")).strip(),
                "language": str(arguments.get("language", "diff") or "diff"),
                "diff": str(arguments.get("diff", "")),
            }
            return _emit(CODE_DIFF_CARD_PREFIX, payload)
        if kind == "reference":
            refs = arguments.get("references") or []
            if not isinstance(refs, list):
                refs = []
            normalized = []
            for item in refs:
                if not isinstance(item, dict):
                    continue
                normalized.append(
                    {
                        "title": str(item.get("title", "")).strip(),
                        "url": str(item.get("url", "")).strip(),
                        "snippet": str(item.get("snippet", "")).strip(),
                    }
                )
            payload = {
                "version": 1,
                "title": title or "References",
                "references": normalized,
            }
            return _emit(REFERENCE_CARD_PREFIX, payload)
        return "Error: emit_card kind must be summary | code_diff | reference"

    def describe_action(self, arguments: dict[str, Any], working_dir: Path) -> str:
        del working_dir
        kind = str(arguments.get("kind", "card")).strip() or "card"
        title = str(arguments.get("title", "")).strip()
        return f"输出卡片 ({kind})" + (f"：{title[:60]}" if title else "")
