"""Tests for skills API."""

from fastapi.testclient import TestClient

from secretary.api.app import app


def test_skill_sources_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/skills/sources")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    assert payload[0]["key"] == "all"
    for item in payload:
        assert {"key", "label", "path", "available", "count"} <= set(item)


def test_skill_catalog_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/skills/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        item = payload[0]
        assert "origin_path" in item
        assert "install_mode" in item
        assert "status" in item
        assert "category" in item


def test_skill_categories_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/skills/categories")
    assert response.status_code == 200
    payload = response.json()
    assert "categories" in payload
    assert "其他" in payload["categories"]


def test_agent_soul_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/agent/soul")
    assert response.status_code == 200
    payload = response.json()
    assert "markdown" in payload
    assert len(payload["markdown"].strip()) > 20
