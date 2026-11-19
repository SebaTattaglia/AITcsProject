"""
app/routers/health.py
Unauthenticated liveness/readiness probe.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas.assistant import IndexStats
from app.services.assistant_service import AssistantService, get_assistant_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(service: AssistantService = Depends(get_assistant_service)) -> dict:
    return {"status": "ok", "index": IndexStats(**service.stats())}
