"""Legacy connector registry — retired.

New integrations must use standard MCP or CLI. Standalone platform connectors
are removed from the runtime (always returns an empty list).
"""

from __future__ import annotations

from secretary.config import Settings
from secretary.connectors.base import BaseConnector


def build_connectors(settings: Settings) -> list[BaseConnector]:
    """Return no connectors — legacy SyncService path is disabled."""
    del settings
    return []
