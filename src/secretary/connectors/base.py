"""Connector base classes."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod

from secretary.config import Settings
from secretary.core.types import ConnectorHealth, ConnectorStatus, MemoryChunk, SourceKind
from secretary.exceptions import ConnectorError


class BaseConnector(ABC):
    source: SourceKind

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch(self) -> list[MemoryChunk]:
        raise NotImplementedError

    def health(self) -> ConnectorHealth:
        if not self.is_configured():
            return ConnectorHealth(
                source=self.source,
                status=ConnectorStatus.NOT_CONFIGURED,
                message="未配置",
            )
        return ConnectorHealth(
            source=self.source,
            status=ConnectorStatus.READY,
            message="已配置",
        )

    @staticmethod
    def run_command(args: list[str], timeout: int = 120) -> str:
        try:
            completed = subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() or exc.stdout.strip() or "unknown error"
            raise ConnectorError(stderr) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConnectorError(f"command timeout: {' '.join(args)}") from exc
        return completed.stdout

    @staticmethod
    def parse_json_output(raw: str) -> object:
        text = raw.strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConnectorError("connector returned invalid JSON") from exc
