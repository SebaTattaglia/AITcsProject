"""
app/services/assistant_service.py
Business layer shared by the FastAPI routers and the MCP server.
Owns the knowledge base, the compiled LangGraph and the review queue of drafts,
and can rebuild the index at runtime (e.g. after an admin approves a draft).
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.document_loader import Document, slugify
from app.services.drafts import DraftConflictError, DraftStore, render_document
from app.services.embeddings import Embedder
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_client import LLMFn, call_llm
from app.services.rag_graph import build_rag_graph

logger = logging.getLogger(__name__)


class AssistantService:
    def __init__(
        self,
        settings: Settings,
        llm: LLMFn = call_llm,
        embedder_factory=None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._embedder_factory = embedder_factory  # tests inject an offline embedder
        self._lock = threading.Lock()
        self._drafts = DraftStore(settings.drafts_dir)
        self._kb, self._graph = self._build()

    def _build(self):
        embedder: Embedder | None = self._embedder_factory() if self._embedder_factory else None
        kb = KnowledgeBase.build(self._settings, embedder=embedder)
        return kb, build_rag_graph(kb, self._llm, self._settings)

    def _snapshot(self):
        with self._lock:
            return self._kb, self._graph

    # ------------------------------------------------------------------
    # Use cases
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        max_attempts: int | None = None,
        top_k: int | None = None,
        doc_type: str | None = None,
    ) -> dict:
        _, graph = self._snapshot()
        state = graph.invoke(
            {
                "question": question,
                "max_attempts": max_attempts,
                "top_k": top_k,
                "doc_type": doc_type,
            }
        )
        draft_id = None
        if state["status"] == "general":
            # Knowledge gap: queue the general answer for human review.
            draft_id = self._drafts.record(question, state["answer"])["id"]
        return {
            "draft_id": draft_id,
            "answer": state["answer"],
            "status": state["status"],
            "citations": state.get("citations", []),
            "attempts": state.get("attempts", 0),
            "final_query": state.get("question", question),
            "best_score": state.get("best_score", 0.0),
            "keyword_overlap": state.get("keyword_overlap", []),
            "llm_used": state.get("llm_used", False),
            "warnings": state.get("warnings", []),
            "trace": state.get("trace", []),
            "retrieved": state.get("retrieved", []),
        }

    def search(
        self,
        query: str,
        k: int = 5,
        doc_type: str | None = None,
        language: str | None = None,
    ) -> list[dict]:
        kb, _ = self._snapshot()
        return [result.to_dict() for result in kb.search(query, k=k, doc_type=doc_type, language=language)]

    def search_snippets(self, query: str, language: str | None = None, k: int = 3) -> list[dict]:
        return self.search(query, k=k, doc_type="snippet", language=language)

    def list_documents(self, doc_type: str | None = None) -> list[Document]:
        kb, _ = self._snapshot()
        return [doc for doc in kb.documents if doc_type is None or doc.doc_type == doc_type]

    def get_document(self, doc_id: str) -> Document | None:
        kb, _ = self._snapshot()
        return kb.get_document(doc_id)

    def stats(self) -> dict:
        kb, _ = self._snapshot()
        return {
            "documents": len(kb.documents),
            "chunks": kb.chunk_count,
            "embedder": kb.embedder_name,
            "llm_configured": self._settings.llm_configured,
            "hybrid_mode": self._settings.hybrid_mode,
            "pending_drafts": self._drafts.counts()["pending"],
        }

    def graph_mermaid(self) -> str:
        _, graph = self._snapshot()
        return graph.get_graph().draw_mermaid()

    # ------------------------------------------------------------------
    # Review queue (admin)
    # ------------------------------------------------------------------

    def list_drafts(self, status: str | None = None) -> list[dict]:
        return self._drafts.list(status)

    def get_draft(self, draft_id: str) -> dict:
        return self._drafts.get(draft_id)

    def update_draft(self, draft_id: str, **changes) -> dict:
        return self._drafts.update(draft_id, **changes)

    def approve_draft(self, draft_id: str, reviewer: str, **changes) -> tuple[dict, dict]:
        """Publish the (optionally edited) draft into data/docs/approved and reindex."""
        draft = self._drafts.update(draft_id, **changes) if any(v is not None for v in changes.values()) else self._drafts.get(draft_id)
        if draft["status"] != "pending":
            raise DraftConflictError(f"Draft is already {draft['status']}")

        doc_id = slugify(draft["doc_id"])
        if not doc_id:
            raise DraftConflictError("doc_id cannot be empty")
        target = self._settings.docs_dir / "approved" / f"{doc_id}.md"
        if self.get_document(doc_id) is not None or target.exists():
            raise DraftConflictError(f"A document with doc_id '{doc_id}' already exists; choose another doc_id")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_document({**draft, "doc_id": doc_id}, reviewer), encoding="utf-8")
        published = target.relative_to(self._settings.docs_dir).as_posix()
        closed = self._drafts.close(draft_id, "approved", reviewer, published_path=published)
        return closed, self.reindex()

    def reject_draft(self, draft_id: str, reviewer: str, note: str | None = None) -> dict:
        return self._drafts.close(draft_id, "rejected", reviewer, note=note)

    def reindex(self) -> dict:
        kb, graph = self._build()  # build outside the lock: queries keep using the old index
        with self._lock:
            self._kb, self._graph = kb, graph
        logger.info("Reindex complete")
        return self.stats()


@lru_cache
def get_assistant_service() -> AssistantService:
    return AssistantService(get_settings())
