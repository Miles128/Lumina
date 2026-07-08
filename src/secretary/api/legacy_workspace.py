"""Legacy Lumina workspace routes.

Shibei is the primary knowledge path now; these endpoints stay available for
compatibility with older workspace and graph UI surfaces.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from secretary.exceptions import IngestError
from secretary.memory.db import MemoryStore
from secretary.memory.graph import GraphBuilder
from secretary.memory.kb import KnowledgeWorkspace
from secretary.services.sync import SyncService

router = APIRouter()


class GraphResponse(BaseModel):
    nodes: list[dict[str, object]]
    edges: list[dict[str, str]]
    layout: str
    legacy_workspace: bool = False


class NoteListResponse(BaseModel):
    notes: list[dict[str, str]]
    legacy_workspace: bool = False


class NoteDetailResponse(BaseModel):
    path: str
    content: str
    legacy_workspace: bool = False


class NoteUpdateRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(max_length=500_000)


def _svc(request: Request) -> Any:
    return request.app.state


@router.get("/api/kb/tree")
def kb_tree(request: Request) -> dict[str, object]:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    return {
        "topics": workspace.topic_tree(),
        "legacy_workspace": True,
        "message": "Legacy Lumina workspace; Shibei is the primary knowledge path.",
    }


@router.get("/api/kb/notes")
def kb_notes(request: Request) -> NoteListResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    notes = workspace.list_notes()
    return NoteListResponse(
        notes=[
            {
                "chunk_id": note.chunk_id,
                "path": note.path,
                "title": note.title,
                "topic": note.topic,
                "source": note.source,
                "updated_at": note.updated_at,
            }
            for note in notes
        ],
        legacy_workspace=True,
    )


@router.get("/api/kb/note")
def kb_note(path: str, request: Request) -> NoteDetailResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    try:
        content = workspace.read_note(path)
    except IngestError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return NoteDetailResponse(path=path, content=content, legacy_workspace=True)


@router.put("/api/kb/note")
def kb_note_update(body: NoteUpdateRequest, request: Request) -> NoteDetailResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    try:
        workspace.write_note(body.path, body.content)
    except IngestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return NoteDetailResponse(path=body.path, content=body.content, legacy_workspace=True)


@router.get("/api/graph")
def graph_data(request: Request, filter: str = "all") -> GraphResponse:
    workspace: KnowledgeWorkspace = _svc(request).workspace
    store: MemoryStore = _svc(request).store
    graph = GraphBuilder(workspace, store).build(filter_mode=filter)
    return GraphResponse(
        nodes=[
            {
                "id": node.id,
                "name": node.name,
                "type": node.node_type,
                **node.meta,
            }
            for node in graph.nodes
        ],
        edges=[
            {"source": edge.source, "target": edge.target, "relation": edge.relation}
            for edge in graph.edges
        ],
        layout=graph.layout,
        legacy_workspace=True,
    )


@router.post("/api/kb/rebuild")
async def kb_rebuild(request: Request) -> dict[str, object]:
    sync_service: SyncService = _svc(request).sync_service
    count = await asyncio.to_thread(sync_service.export_kb_from_memory)
    return {"exported": count, "legacy_workspace": True}
