"""Pytest configuration."""

from __future__ import annotations

import os

os.environ.setdefault("SECRETARY_AUTO_SYNC_ENABLED", "false")
os.environ.setdefault("SECRETARY_BRIEFING_ENABLED", "false")
