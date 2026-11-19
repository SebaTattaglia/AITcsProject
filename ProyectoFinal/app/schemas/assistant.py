"""
app/schemas/assistant.py
Pydantic contracts for the knowledge assistant API.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DocType(str, Enum):
    standard = "standard"
    guide = "guide"
    troubleshooting = "troubleshooting"
    runbook = "runbook"
    snippet = "snippet"
    issue = "issue"
    reference = "reference"


# --- Ask -------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000, examples=["How should I retry calls to a flaky downstream API?"])
    max_attempts: int | None = Field(default=None, ge=0, le=5, description="Max rewrite_question loops")
    top_k: int | None = Field(default=None, ge=1, le=10)
    doc_type: DocType | None = None


class Citation(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    source_path: str
    section: str
    score: float


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    source_path: str
    section: str
    language: str | None = None
    score: float
    text: str


class AskResponse(BaseModel):
    answer: str
    status: Literal["answered", "general", "no_answer", "fallback", "degraded"]
    draft_id: str | None = Field(default=None, description="Review-queue draft created for a general answer")
    citations: list[Citation]
    attempts: int
    final_query: str
    best_score: float
    keyword_overlap: list[str]
    llm_used: bool
    warnings: list[str]
    trace: list[str]
    retrieved: list[RetrievedChunk] = []


# --- Search ----------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    doc_type: DocType | None = None
    language: str | None = Field(default=None, examples=["python"])


class SearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunk]


# --- Documents -------------------------------------------------------------

class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    source_path: str
    language: str | None = None
    tags: list[str] = []


class DocumentDetail(DocumentSummary):
    text: str


class IndexStats(BaseModel):
    documents: int
    chunks: int
    embedder: str
    llm_configured: bool
    hybrid_mode: bool
    pending_drafts: int


class Me(BaseModel):
    role: str
    key_hint: str


# --- Review queue (admin) ----------------------------------------------------

class Draft(BaseModel):
    id: str
    status: Literal["pending", "approved", "rejected"]
    question: str
    questions: list[str]
    asked_count: int
    title: str
    doc_id: str
    doc_type: str
    tags: list[str]
    content: str
    created_at: str
    updated_at: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    published_path: str | None = None


class DraftUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    doc_id: str | None = Field(default=None, min_length=3, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]*$")
    doc_type: DocType | None = None
    tags: list[str] | None = None
    content: str | None = Field(default=None, min_length=20, max_length=20000)


class ApproveResponse(BaseModel):
    draft: Draft
    index: IndexStats


class RejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
