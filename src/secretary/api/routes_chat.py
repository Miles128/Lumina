"""Chat, identity, progress, confirm, uploads, and thread routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from secretary.agent.chat_service import ChatService
from secretary.agent.llm_client import llm_usage_scope
from secretary.agent.progress_hub import ProgressHub
from secretary.agent.turn_cancel import begin_turn, end_turn, request_cancel
from secretary.api.deps import (
    build_progress_callback,
    finish_progress,
    svc,
    to_chat_response,
)
from secretary.api.schemas import (
    ChatCancelRequest,
    ChatRequest,
    ChatResponse,
    ChatThreadActiveLeafRequest,
    ChatThreadCreateRequest,
    ChatThreadCurrentRequest,
    ChatThreadRestoreRequest,
    ChatThreadRollbackRequest,
    ChatThreadsPutRequest,
    ChatUploadsFromPathsRequest,
    ConfirmActionRequest,
)
from secretary.config import settings
from secretary.services.chat_uploads import (
    DEFAULT_ATTACHMENT_PROMPT,
    MAX_UPLOAD_FILES,
    copy_local_path,
    save_upload_bytes,
)

router = APIRouter(tags=["chat"])


@router.get("/api/chat/progress/{trace_id}")
async def chat_progress(request: Request, trace_id: str) -> StreamingResponse:
    hub: ProgressHub = request.app.state.progress_hub
    return StreamingResponse(
        hub.stream(trace_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/api/chat/cancel")
def cancel_chat(body: ChatCancelRequest) -> dict[str, bool]:
    return {"cancelled": request_cancel(body.trace_id.strip())}


@router.get("/api/identity/author")
def identity_author() -> dict[str, str]:
    from secretary.agent.identity import get_author_reply

    return {"reply": get_author_reply()}


@router.get("/api/identity/intro")
def identity_intro() -> dict[str, str]:
    from secretary.agent.identity import get_identity_reply

    return {"reply": get_identity_reply()}


@router.post("/api/chat")
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    chat_service: ChatService = svc(request).chat_service
    attachments = [p.strip() for p in body.attachments if isinstance(p, str) and p.strip()]
    message = body.message.strip()
    if not message and not attachments:
        raise HTTPException(status_code=400, detail="message or attachments required")
    if not message:
        message = DEFAULT_ATTACHMENT_PROMPT
    author_turn = chat_service.is_author_turn(message)
    identity_turn = chat_service.is_identity_turn(message)
    trace_id = "" if (author_turn or identity_turn) else body.trace_id.strip()
    thread_id = body.thread_id.strip()
    progress = build_progress_callback(request, trace_id)
    cancel_event = begin_turn(trace_id) if trace_id else None
    if trace_id:
        request.app.state.session_store.start_turn(
            trace_id=trace_id,
            thread_id=thread_id,
            user_message=message,
        )
    keep_turn = False
    try:
        with llm_usage_scope() as usage:
            result = chat_service.reply(
                message,
                progress_callback=progress,
                thread_id=thread_id or None,
                trace_id=trace_id or None,
                parent_message_id=body.parent_message_id or None,
                working_dir=body.working_dir or None,
                attachments=attachments,
                cancel_check=cancel_event.is_set if cancel_event is not None else None,
            )
        keep_turn = bool(result.pending_confirmation)
        return to_chat_response(result, usage)
    finally:
        finish_progress(request, trace_id, keep_turn=keep_turn)
        if trace_id:
            end_turn(trace_id)


@router.post("/api/chat/uploads")
async def upload_chat_files(
    files: Annotated[list[UploadFile], File()],
    thread_id: Annotated[str, Form()] = "",
) -> dict[str, object]:
    uploads = list(files)
    if not uploads:
        raise HTTPException(status_code=400, detail="no files")
    if len(uploads) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"max {MAX_UPLOAD_FILES} files")
    data_dir = settings.resolved_data_dir()
    saved: list[dict[str, object]] = []
    try:
        for upload in uploads:
            content = await upload.read()
            item = save_upload_bytes(
                data_dir,
                thread_id=thread_id,
                filename=upload.filename or "file",
                content=content,
            )
            saved.append(item.as_dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"files": saved}


@router.post("/api/chat/uploads/from-paths")
def upload_chat_files_from_paths(
    body: ChatUploadsFromPathsRequest,
) -> dict[str, object]:
    if not body.paths:
        raise HTTPException(status_code=400, detail="no paths")
    if len(body.paths) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"max {MAX_UPLOAD_FILES} files")
    data_dir = settings.resolved_data_dir()
    saved: list[dict[str, object]] = []
    try:
        for raw in body.paths:
            item = copy_local_path(data_dir, thread_id=body.thread_id, source=raw)
            saved.append(item.as_dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"files": saved}


@router.post("/api/chat/confirm")
def confirm_action(request: Request, body: ConfirmActionRequest) -> ChatResponse:
    chat_service: ChatService = svc(request).chat_service
    trace_id = body.trace_id.strip()
    thread_id = body.thread_id.strip()
    progress = build_progress_callback(request, trace_id)
    cancel_event = begin_turn(trace_id) if trace_id else None
    if trace_id and request.app.state.session_store.get_turn(trace_id) is None:
        request.app.state.session_store.start_turn(
            trace_id=trace_id,
            thread_id=thread_id,
            user_message="confirm",
        )
    keep_turn = False
    try:
        with llm_usage_scope() as usage:
            result = chat_service.confirm_action(
                body.approved,
                grant_permanent_read=body.grant_permanent_read,
                grant_session_write=body.grant_session_write,
                progress_callback=progress,
                thread_id=thread_id or None,
                trace_id=trace_id or None,
                cancel_check=cancel_event.is_set if cancel_event is not None else None,
            )
        keep_turn = bool(result.pending_confirmation)
        return to_chat_response(result, usage)
    finally:
        finish_progress(request, trace_id, keep_turn=keep_turn)
        if trace_id:
            end_turn(trace_id)


@router.delete("/api/chat/history")
def clear_chat_history(request: Request) -> dict[str, str]:
    chat_service: ChatService = svc(request).chat_service
    chat_service.clear_history()
    return {"status": "ok"}


@router.get("/api/chat/threads")
def get_chat_threads(request: Request) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.list_threads()


@router.post("/api/chat/threads")
def create_chat_thread(request: Request, body: ChatThreadCreateRequest) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.create_thread(title=body.title.strip() or "新对话")


@router.put("/api/chat/threads/current")
def set_current_chat_thread(request: Request, body: ChatThreadCurrentRequest) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.set_current_thread(body.thread_id.strip())


@router.delete("/api/chat/threads/{thread_id}")
def delete_chat_thread(request: Request, thread_id: str) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.delete_thread(thread_id.strip())


@router.put("/api/chat/threads")
def put_chat_threads(request: Request, body: ChatThreadsPutRequest) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.save_threads(current_id=body.current_id, threads=body.threads)


@router.put("/api/chat/threads/{thread_id}/active-leaf")
def set_chat_thread_active_leaf(
    request: Request,
    thread_id: str,
    body: ChatThreadActiveLeafRequest,
) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.set_thread_active_leaf(thread_id.strip(), body.leaf_id.strip())


@router.get("/api/chat/threads/{thread_id}/tree")
def get_chat_thread_tree(request: Request, thread_id: str) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.thread_tree(thread_id.strip())


@router.post("/api/chat/threads/{thread_id}/rollback")
def rollback_chat_thread(
    request: Request,
    thread_id: str,
    body: ChatThreadRollbackRequest,
) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.rollback_thread(thread_id.strip(), body.to_message_id.strip())


@router.post("/api/chat/threads/{thread_id}/restore")
def restore_chat_thread(
    request: Request,
    thread_id: str,
    body: ChatThreadRestoreRequest,
) -> dict[str, object]:
    chat_service: ChatService = svc(request).chat_service
    return chat_service.restore_thread(thread_id.strip(), body.message_id.strip())


