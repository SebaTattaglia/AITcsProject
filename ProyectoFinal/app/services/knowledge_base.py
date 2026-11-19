"""
app/services/knowledge_base.py
In-memory vector index over the chunked documentation.
Embedders that are expensive to run (cacheable=True) are cached on disk, keyed by a
hash of embedder + corpus, so restarting the API does not re-embed unchanged docs.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from app.core.config import Settings
from app.services.chunker import Chunk, TokenCounter, chunk_document
from app.services.document_loader import Document, load_documents
from app.services.embeddings import Embedder, get_embedder

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk: Chunk
    score: float

    def to_dict(self) -> dict:
        return {**asdict(self.chunk), "score": round(self.score, 4)}


def _embed_corpus(embedder: Embedder, texts: list[str], cache_dir: Path) -> np.ndarray:
    embedder.fit(texts)
    if not embedder.cacheable:
        return embedder.embed_documents(texts)

    digest = hashlib.sha256((embedder.name + "\x00" + "\x1e".join(texts)).encode()).hexdigest()[:16]
    cache_path = cache_dir / f"embeddings-{digest}.npy"
    if cache_path.exists():
        logger.info("Loaded cached embeddings from %s", cache_path.name)
        return np.load(cache_path)

    matrix = embedder.embed_documents(texts)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, matrix)
    return matrix


class KnowledgeBase:
    def __init__(
        self,
        documents: list[Document],
        chunks: list[Chunk],
        embedder: Embedder,
        matrix: np.ndarray,
    ) -> None:
        self._documents = {doc.doc_id: doc for doc in documents}
        self._chunks = chunks
        self._embedder = embedder
        self._matrix = matrix

    @classmethod
    def build(cls, settings: Settings, embedder: Embedder | None = None) -> "KnowledgeBase":
        documents = load_documents(settings.docs_dir)
        if not documents:
            raise ValueError(f"No supported documents found in {settings.docs_dir}")

        counter = TokenCounter()
        chunks = [
            chunk
            for doc in documents
            for chunk in chunk_document(
                doc, counter, settings.chunk_tokens, settings.chunk_overlap_tokens
            )
        ]
        texts = [chunk.embedding_text for chunk in chunks]

        embedder = embedder or get_embedder()
        matrix = _embed_corpus(embedder, texts, settings.index_dir)

        logger.info(
            "Knowledge base ready: %d documents, %d chunks, embedder=%s",
            len(documents), len(chunks), embedder.name,
        )
        return cls(documents, chunks, embedder, matrix)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def embedder_name(self) -> str:
        return self._embedder.name

    @property
    def documents(self) -> list[Document]:
        return list(self._documents.values())

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def get_document(self, doc_id: str) -> Document | None:
        return self._documents.get(doc_id)

    def has_document(self, doc_id: str) -> bool:
        return doc_id in self._documents

    def search(
        self,
        query: str,
        k: int = 4,
        doc_type: str | None = None,
        language: str | None = None,
    ) -> list[SearchResult]:
        if not query.strip():
            return []

        scores = self._matrix @ self._embedder.embed_query(query)
        results: list[SearchResult] = []
        for index in np.argsort(-scores):
            chunk = self._chunks[index]
            if doc_type and chunk.doc_type != doc_type:
                continue
            if language and (chunk.language or "").lower() != language.lower():
                continue
            results.append(SearchResult(chunk=chunk, score=float(scores[index])))
            if len(results) >= k:
                break
        return results
