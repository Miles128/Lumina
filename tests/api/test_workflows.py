"""HTTP tests for /api/workflows (F26 slice E)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from secretary.api.app import app
from secretary.workflow.scheduler import WorkflowScheduler
from secretary.workflow.store import WorkflowStore


def test_workflows_crud_and_run(tmp_path: Path) -> None:
    client = TestClient(app)
    original_store = app.state.workflow_store
    original_scheduler = app.state.workflow_scheduler
    store = WorkflowStore(tmp_path / "workflows")

    def skill_runner(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        assert name == "echo"
        return {"text": inputs.get("topic", "")}

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"summary": prompt}

    app.state.workflow_store = store
    app.state.workflow_scheduler = WorkflowScheduler(
        skill_runner=skill_runner,
        agent_runner=agent_runner,
    )
    name = "demo_flow"
    try:
        listed = client.get("/api/workflows")
        assert listed.status_code == 200
        assert listed.json()["workflows"] == []

        payload = {
            "name": name,
            "version": 1,
            "inputs_schema": {"topic": {"type": "string"}},
            "outputs_schema": {"summary": {"type": "string"}},
            "nodes": [
                {
                    "id": "n1",
                    "kind": "skill",
                    "config": {"skill_name": "echo"},
                    "inputs_schema": {},
                    "outputs_schema": {"text": "string"},
                },
                {
                    "id": "n2",
                    "kind": "agent",
                    "config": {"prompt_template": "总结：{{n1.text}}"},
                    "inputs_schema": {},
                    "outputs_schema": {"summary": "string"},
                },
            ],
            "edges": [{"from": "n1", "to": "n2", "port": "default"}],
        }
        saved = client.put(f"/api/workflows/{name}", json=payload)
        assert saved.status_code == 200
        assert saved.json()["name"] == name

        got = client.get(f"/api/workflows/{name}")
        assert got.status_code == 200
        assert len(got.json()["nodes"]) == 2

        listed = client.get("/api/workflows")
        assert any(item["name"] == name for item in listed.json()["workflows"])

        ran = client.post(f"/api/workflows/{name}/run", json={"inputs": {"topic": "hi"}})
        assert ran.status_code == 200
        body = ran.json()
        assert body["status"] == "completed"
        assert body["run_id"]
        assert "总结：hi" in body["node_outputs"]["n2"]["summary"]
        assert (tmp_path / "workflows" / "runs" / f"{body['run_id']}.json").is_file()

        deleted = client.delete(f"/api/workflows/{name}")
        assert deleted.status_code == 200
        missing = client.get(f"/api/workflows/{name}")
        assert missing.status_code == 404
    finally:
        app.state.workflow_store = original_store
        app.state.workflow_scheduler = original_scheduler


def test_workflows_templates_and_resume(tmp_path: Path) -> None:
    client = TestClient(app)
    original_store = app.state.workflow_store
    original_scheduler = app.state.workflow_scheduler
    store = WorkflowStore(tmp_path / "workflows")

    def agent_runner(prompt: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"reply": prompt}

    app.state.workflow_store = store
    app.state.workflow_scheduler = WorkflowScheduler(agent_runner=agent_runner)
    try:
        templates = client.get("/api/workflows/templates")
        assert templates.status_code == 200
        ids = {item["id"] for item in templates.json()["templates"]}
        assert "research" in ids

        created = client.post(
            "/api/workflows/templates/research",
            json={"name": "research_demo"},
        )
        assert created.status_code == 200
        assert created.json()["name"] == "research_demo"

        paused = client.post(
            "/api/workflows/research_demo/run",
            json={"inputs": {"topic": "Lumina"}},
        )
        assert paused.status_code == 200
        body = paused.json()
        assert body["status"] == "paused"
        assert body["pause_node_id"] == "review"
        run_id = body["run_id"]

        resumed = client.post(
            f"/api/workflows/runs/{run_id}/resume",
            json={"approved": True, "note": "ok"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "completed"
    finally:
        app.state.workflow_store = original_store
        app.state.workflow_scheduler = original_scheduler


def test_agent_policy_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/agent/policy")
    assert response.status_code == 200
    body = response.json()
    assert body["max_spawn_depth"] == 1
    assert any(item["name"] == "worker" for item in body["archetypes"])
