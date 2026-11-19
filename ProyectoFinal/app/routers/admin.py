"""
app/routers/admin.py
Review queue for general answers (Incident2KB-style pending -> approved flow).
Every route requires the admin role.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import Principal, require_role
from app.schemas.assistant import ApproveResponse, Draft, DraftUpdate, IndexStats, RejectRequest
from app.services.assistant_service import AssistantService, get_assistant_service
from app.services.drafts import DraftConflictError, DraftNotFoundError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

AdminOnly = Depends(require_role("admin"))


def _reviewer(principal: Principal) -> str:
    return f"{principal.role}:{principal.key_hint}"


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")


def _conflict(exc: DraftConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/drafts", response_model=list[Draft])
def list_drafts(
    status_filter: Literal["pending", "approved", "rejected"] | None = Query(default=None, alias="status"),
    _: Principal = AdminOnly,
    service: AssistantService = Depends(get_assistant_service),
):
    """Drafts sorted by how often the question was asked (biggest documentation gaps first)."""
    return service.list_drafts(status_filter)


@router.get("/drafts/{draft_id}", response_model=Draft)
def get_draft(
    draft_id: str,
    _: Principal = AdminOnly,
    service: AssistantService = Depends(get_assistant_service),
):
    try:
        return service.get_draft(draft_id)
    except DraftNotFoundError:
        raise _not_found() from None


@router.patch("/drafts/{draft_id}", response_model=Draft)
def update_draft(
    draft_id: str,
    payload: DraftUpdate,
    _: Principal = AdminOnly,
    service: AssistantService = Depends(get_assistant_service),
):
    """Save edits to a pending draft without publishing it."""
    try:
        return service.update_draft(draft_id, **payload.model_dump(mode="json", exclude_none=True))
    except DraftNotFoundError:
        raise _not_found() from None
    except DraftConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/drafts/{draft_id}/approve", response_model=ApproveResponse)
def approve_draft(
    draft_id: str,
    payload: DraftUpdate | None = None,
    principal: Principal = AdminOnly,
    service: AssistantService = Depends(get_assistant_service),
):
    """Publish the draft as a company document (data/docs/approved/) and rebuild the index."""
    changes = payload.model_dump(mode="json", exclude_none=True) if payload else {}
    try:
        draft, stats = service.approve_draft(draft_id, _reviewer(principal), **changes)
    except DraftNotFoundError:
        raise _not_found() from None
    except DraftConflictError as exc:
        raise _conflict(exc) from exc
    return {"draft": draft, "index": IndexStats(**stats)}


@router.post("/drafts/{draft_id}/reject", response_model=Draft)
def reject_draft(
    draft_id: str,
    payload: RejectRequest | None = None,
    principal: Principal = AdminOnly,
    service: AssistantService = Depends(get_assistant_service),
):
    try:
        return service.reject_draft(draft_id, _reviewer(principal), note=payload.note if payload else None)
    except DraftNotFoundError:
        raise _not_found() from None
    except DraftConflictError as exc:
        raise _conflict(exc) from exc
