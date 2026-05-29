"""Connector registry."""

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
    return [
        FeishuConnector(settings),
        EmailConnector(settings),
        WeReadConnector(settings),
        XiaohongshuConnector(settings),
        WeixinOAConnector(settings),
        CloudDriveConnector(settings),
    ]
