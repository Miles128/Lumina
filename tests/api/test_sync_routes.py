"""HTTP tests for sync endpoints with mocked SyncService."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.core.types import ConnectorHealth, ConnectorStatus, SourceKind
from secretary.services.sync import SyncResult


def test_sync_all_and_one_mocked() -> None:
    client = TestClient(app)
    original = app.state.sync_service
    health = ConnectorHealth(
        source=SourceKind.FEISHU,
        status=ConnectorStatus.READY,
        message="ok",
    )
    fake = MagicMock()
    fake.sync_all.return_value = [
        SyncResult(source=SourceKind.FEISHU, inserted=3, health=health),
    ]
    fake.sync_source.return_value = SyncResult(
        source=SourceKind.FEISHU,
        inserted=1,
        health=health,
    )
    app.state.sync_service = fake
    try:
        all_resp = client.post("/api/sync")
        assert all_resp.status_code == 200
        payload = all_resp.json()
        assert isinstance(payload, list)
        assert payload[0]["source"] == "feishu"
        assert payload[0]["inserted"] == 3
        fake.sync_all.assert_called_once()

        one = client.post("/api/sync/feishu")
        assert one.status_code == 200
        body = one.json()
        assert body["source"] == "feishu"
        assert body["inserted"] == 1
        assert body["status"] == "ready"
        fake.sync_source.assert_called_once()
    finally:
        app.state.sync_service = original
