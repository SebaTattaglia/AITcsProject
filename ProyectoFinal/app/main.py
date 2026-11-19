"""
app/main.py
Application entry point: connects the layers.

Run:  uvicorn app.main:app --reload --port 8001
UI:   http://127.0.0.1:8001/
Docs: http://127.0.0.1:8001/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import PROJECT_ROOT
from app.routers import admin, assistant, health
from app.services.assistant_service import get_assistant_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the index at startup instead of on the first request.
    # Honours dependency overrides so tests can inject an offline service.
    app.dependency_overrides.get(get_assistant_service, get_assistant_service)()
    yield


app = FastAPI(
    title="Application Development Knowledge Assistant",
    version="1.0.0",
    description=(
        "Agentic RAG assistant for IT teams: coding standards, runbooks, troubleshooting "
        "guides, code snippets and issue tickets, answered with mandatory [doc_id] citations."
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(assistant.router)
app.include_router(admin.router)

# Developer chat UI (static HTML/CSS/JS, same origin as the API: no CORS needed).
app.mount("/ui", StaticFiles(directory=PROJECT_ROOT / "frontend", html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")
