"""Connector tests with mocked CLI output."""

from __future__ import annotations

import json
from pathlib import Path

from secretary.config import Settings
from secretary.connectors.feishu import FeishuConnector


def test_feishu_fetch_parses_calendar_and_tasks(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")

    def fake_run(args: list[str], timeout: int = 120) -> str:
        if args[:3] == ["lark-cli", "calendar", "+agenda"]:
            return json.dumps(
                [{"summary": "周会", "start_time": "10:00", "description": "同步进度"}],
                ensure_ascii=False,
            )
        if args[:3] == ["lark-cli", "task", "+get-my-tasks"]:
            return json.dumps(
                [{"summary": "写周报", "status": "todo"}],
                ensure_ascii=False,
            )
        return "{}"

    connector = FeishuConnector(settings)
    connector.run_command = fake_run  # type: ignore[method-assign]
    chunks = connector.fetch()
    titles = {chunk.title for chunk in chunks}
    assert any("周会" in title for title in titles)
    assert any("写周报" in title for title in titles)
