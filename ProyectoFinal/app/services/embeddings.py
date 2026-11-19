"""
app/services/embeddings.py
Local vector representations for retrieval (Lesson 3). Vectors are L2-normalized,
so cosine similarity is just a dot product.

The LLM runs behind an n8n webhook that does not expose an embeddings endpoint, so
retrieval uses local TF-IDF. Any class matching the Embedder protocol (for example a
sentence-transformers model) can be plugged into KnowledgeBase.build().
"""
from __future__ import annotations

import re
from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer


class Embedder(Protocol):
    name: str
    cacheable: bool

    def fit(self, texts: list[str]) -> None: ...

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype("float32")


_TOKEN_RE = re.compile(r"(?u)\b\w\w+\b")


def _light_stem(token: str) -> str:
    """Tiny suffix stripper so "retries/retry" and "messages/message" share a term."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    for suffix in ("ing", "ed", "s"):
        if token.endswith(suffix) and not token.endswith("ss") and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def _analyze(text: str) -> list[str]:
    return [_light_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in ENGLISH_STOP_WORDS]


class TfidfEmbedder:
    name = "tfidf"
    cacheable = False  # cheap to rebuild, and the vocabulary depends on the corpus

    def __init__(self) -> None:
        self._vectorizer = TfidfVectorizer(analyzer=_analyze, sublinear_tf=True)

    def fit(self, texts: list[str]) -> None:
        self._vectorizer.fit(texts)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(self._vectorizer.transform(texts).toarray())

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


def get_embedder() -> Embedder:
    return TfidfEmbedder()
