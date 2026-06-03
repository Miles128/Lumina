"""Pytest configuration."""

from __future__ import annotations

import os

os.environ.setdefault("SECRETARY_AUTO_SYNC_ENABLED", "false")
os.environ.setdefault("SECRETARY_BRIEFING_ENABLED", "false")
os.environ.setdefault("SECRETARY_THINK_ENABLED", "false")
os.environ.setdefault("SECRETARY_MEMORY_SUMMARY_ENABLED", "false")
os.environ.setdefault("PROMPT_GATE_ENABLED", "false")
