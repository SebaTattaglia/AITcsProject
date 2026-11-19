"""
app/routers/assistant.py
HTTP routes only: validation, auth and status codes. Logic lives in AssistantService.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import Principal, require_auth, require_role
from app.schemas.assistant import (
    AskRequest,
    AskResponse,
    DocType,
    DocumentDetail,
    DocumentSummary,
    IndexStats,
    Me,
    SearchRequest,
    SearchResponse,
)
from app.services.assistant_service import AssistantService, get_assistant_service

router = APIRouter(prefix="/api/v1", tags=["knowledge-assistant"])


def _enum_value(value: DocType | None) -> str | None:
    return value.value if value else None


@router.get("/me", response_model=Me)
def whoami(principal: Principal = Depends(require_auth)):
    """Role of the current API key (the UI shows the review queue only to admins)."""
    return {"role": principal.role, "key_hint": principal.key_hint}


@router.post("/assistant/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    _: Principal = Depends(require_auth),
    service: AssistantService = Depends(get_assistant_service),
):
    """Answer a technical question with the agentic RAG graph and [doc_id] citations."""
    return service.ask(
        payload.question,
        max_attempts=payload.max_attempts,
        top_k=payload.top_k,
        doc_type=_enum_value(payload.doc_type),
    )


@router.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    _: Principal = Depends(require_auth),
    service: AssistantService = Depends(get_assistant_service),
):
    """Semantic search over the documentation, without generation."""
    results = service.search(
        payload.query, k=payload.k, doc_type=_enum_value(payload.doc_type), language=payload.language
    )
    return {"query": payload.query, "results": results}


@router.get("/snippets/search", response_model=SearchResponse)
def search_snippets(
    q: str = Query(min_length=2, max_length=500),
    language: str | None = None,
    k: int = Query(default=3, ge=1, le=10),
    _: Principal = Depends(require_auth),
    service: AssistantService = Depends(get_assistant_service),
):
    """Code retrieval: find reusable snippets, optionally filtered by language."""
    results = service.search_snippets(q, language=language, k=k)
    return {"query": q, "results": results}


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    doc_type: DocType | None = None,
    _: Principal = Depends(require_auth),
    service: AssistantService = Depends(get_assistant_service),
):
    return [asdict(doc) for doc in service.list_documents(_enum_value(doc_type))]


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(
    doc_id: str,
    _: Principal = Depends(require_auth),
    service: AssistantService = Depends(get_assistant_service),
):
    doc = service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return asdict(doc)


@router.post("/admin/reindex", response_model=IndexStats)
def reindex(
    _: Principal = Depends(require_role("admin")),
    service: AssistantService = Depends(get_assistant_service),
):
    """Reload data/docs and rebuild the index without restarting the server."""
    return service.reindex()
