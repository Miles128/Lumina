"""Artifact panel APIs: workspace/sandbox tree + file preview."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from secretary.api.deps import svc
from secretary.config import settings
from secretary.services import artifacts as artifact_service

router = APIRouter(tags=["artifacts"])


@router.get("/api/artifacts/context")
def artifacts_context(
    request: Request,
    thread_id: str = Query(default=""),
) -> dict[str, object]:
    store = svc(request).agent_config_store
    data_dir = settings.resolved_data_dir()
    roots = artifact_service.allowed_roots(
        data_dir=data_dir,
        thread_id=thread_id,
        agent_config=store,
    )
    workspace = next((r["path"] for r in roots if r["id"] == "workspace"), "")
    sandbox = next((r["path"] for r in roots if r["id"] == "sandbox"), "")
    return {
        "thread_id": thread_id or "_default",
        "workspace": workspace,
        "sandbox": sandbox,
        "roots": roots,
    }


@router.get("/api/artifacts/tree")
def artifacts_tree(
    request: Request,
    path: str = Query(...),
    thread_id: str = Query(default=""),
    depth: int = Query(default=3, ge=1, le=6),
) -> dict[str, object]:
    store = svc(request).agent_config_store
    try:
        return artifact_service.list_tree(
            path,
            data_dir=settings.resolved_data_dir(),
            thread_id=thread_id,
            agent_config=store,
            depth=depth,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/artifacts/file")
def artifacts_file(
    request: Request,
    path: str = Query(...),
    thread_id: str = Query(default=""),
) -> dict[str, object]:
    store = svc(request).agent_config_store
    try:
        return artifact_service.preview_file(
            path,
            data_dir=settings.resolved_data_dir(),
            thread_id=thread_id,
            agent_config=store,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/artifacts/raw")
def artifacts_raw(
    request: Request,
    path: str = Query(...),
    thread_id: str = Query(default=""),
) -> FileResponse:
    store = svc(request).agent_config_store
    try:
        file_path = artifact_service.resolve_raw_file(
            path,
            data_dir=settings.resolved_data_dir(),
            thread_id=thread_id,
            agent_config=store,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=None,
        content_disposition_type="inline",
    )