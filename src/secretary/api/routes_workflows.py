"""Workflow CRUD and run API (F26)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from secretary.workflow.models import WorkflowDef
from secretary.workflow.scheduler import WorkflowRunError, WorkflowRunResult, WorkflowScheduler
from secretary.workflow.store import WorkflowStore, WorkflowStoreError
from secretary.workflow.templates_loader import list_templates, load_template

router = APIRouter(tags=["workflows"])


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowResumeRequest(BaseModel):
    approved: bool = True
    note: str = ""


class WorkflowFromTemplateRequest(BaseModel):
    name: str = ""


def _result_payload(
    *,
    run_id: str,
    name: str,
    started: str,
    inputs: dict[str, Any],
    result: WorkflowRunResult,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "workflow": name,
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "status": result.status,
        "error": result.error,
        "inputs": inputs,
        "pause_node_id": result.pause_node_id,
        "pause_prompt": result.pause_prompt,
        "pause_kind": result.pause_kind,
        "checkpoint": result.checkpoint,
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


@router.get("/api/workflows/templates")
def get_workflow_templates() -> dict[str, object]:
    return {"templates": list_templates()}


@router.post("/api/workflows/templates/{template_id}")
def create_from_template(
    request: Request,
    template_id: str,
    body: WorkflowFromTemplateRequest | None = None,
) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    try:
        workflow = load_template(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = (body.name if body else "").strip() or workflow.name or template_id
    workflow.name = name
    try:
        store.save(workflow)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.get(name).to_dict()


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

    payload = _result_payload(
        run_id=run_id, name=name, started=started, inputs=inputs, result=result
    )
    store.save_run(run_id, payload)
    return payload


@router.post("/api/workflows/runs/{run_id}/resume")
def resume_workflow_run(
    request: Request,
    run_id: str,
    body: WorkflowResumeRequest | None = None,
) -> dict[str, object]:
    store: WorkflowStore = request.app.state.workflow_store
    scheduler: WorkflowScheduler = request.app.state.workflow_scheduler
    try:
        prior = store.get_run(run_id)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if prior.get("status") != "paused":
        raise HTTPException(status_code=400, detail="run is not paused")
    name = str(prior.get("workflow") or "")
    try:
        workflow = store.get(name)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    checkpoint = dict(prior.get("checkpoint") or {})
    inputs = dict(prior.get("inputs") or checkpoint.get("inputs") or {})
    decision = body or WorkflowResumeRequest()
    started = datetime.now(UTC).isoformat()
    try:
        result = scheduler.run(
            workflow,
            inputs=inputs,
            checkpoint=checkpoint,
            resume_payload={"approved": decision.approved, "note": decision.note},
        )
    except WorkflowRunError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = _result_payload(
        run_id=run_id, name=name, started=started, inputs=inputs, result=result
    )
    store.save_run(run_id, payload)
    return payload
