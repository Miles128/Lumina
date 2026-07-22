"""Legacy connector registry (frozen).

New integrations must use standard MCP or CLI — do not add platform-specific
connectors here. See docs/PRD.md §1 / Open Decisions.
"""

from __future__ import annotations

from secretary.config import Settings
from secretary.connectors.base import BaseConnector
from secretary.connectors.cloud_drive import CloudDriveConnector
from secretary.connectors.email_imap import EmailConnector
from secretary.connectors.feishu import FeishuConnector
from secretary.connectors.weixin_oa import WeixinOAConnector
from secretary.connectors.weread import WeReadConnector
from secretary.connectors.xiaohongshu import XiaohongshuConnector


def build_connectors(settings: Settings) -> list[BaseConnector]:
    """Return frozen legacy connectors. Prefer MCP/CLI for new capability."""
    return [
        FeishuConnector(settings),
        EmailConnector(settings),
        WeReadConnector(settings),
        XiaohongshuConnector(settings),
        WeixinOAConnector(settings),
        CloudDriveConnector(settings),
    ]
