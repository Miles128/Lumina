"""Workflow CRUD and run API (F26)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from secretary.workflow.models import WorkflowDef
from secretary.workflow.scheduler import WorkflowRunError, WorkflowScheduler
from secretary.workflow.store import WorkflowStore, WorkflowStoreError

router = APIRouter(tags=["workflows"])


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/workflows")
def list_workflows(request: Request) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    items: list[dict[str, object]] = []
    for name in store.list_names():
        try:
            workflow = store.get(name)
            items.append({"name": workflow.name, "version": workflow.version})
        except WorkflowStoreError:
            items.append({"name": name, "version": 0})
    return {"workflows": items}


@router.get("/api/workflows/{name}")
def get_workflow(request: Request, name: str) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    try:
        return store.get(name).to_dict()
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/api/workflows/{name}")
def put_workflow(request: Request, name: str, body: dict[str, Any]) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    payload = dict(body)
    payload["name"] = name
    workflow = WorkflowDef.from_dict(payload)
    try:
        store.save(workflow)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.get(name).to_dict()


@router.delete("/api/workflows/{name}")
def delete_workflow(request: Request, name: str) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    try:
        store.delete(name)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "name": name}


@router.post("/api/workflows/{name}/run")
def run_workflow(
    request: Request,
    name: str,
    body: WorkflowRunRequest | None = None,
) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    scheduler: WorkflowScheduler = request.app.state.workflow_scheduler
    try:
        workflow = store.get(name)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    inputs = dict((body.inputs if body else {}) or {})
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(UTC).isoformat()
    try:
        result = scheduler.run(workflow, inputs=inputs)
    except WorkflowRunError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = {
        "run_id": run_id,
        "workflow": name,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "status": result.status,
        "error": result.error,
        "inputs": inputs,
        "steps": [
            {
                "node_id": step.node_id,
                "kind": step.kind,
                "status": step.status,
                "outputs": step.outputs,
                "error": step.error,
            }
            for step in result.steps
        ],
        "node_outputs": result.node_outputs,
    }
    store.save_run(run_id, payload)
    return payload
