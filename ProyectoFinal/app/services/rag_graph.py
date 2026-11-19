"""
app/services/rag_graph.py
Agentic RAG workflow (Lesson 7), adapted to developer documentation:

    START -> initialize -> retrieve -> grade_context --relevant--> generate_answer --> END
                              ^              |                          |
                              |          weak context,           model found no answer
                              |          attempts left            (hybrid mode only)
                              |              v                          |
                              +------ rewrite_question                  v
                                             |                    general_answer -> END
                                    weak context, no attempts left      ^
                                             +--- hybrid mode ----------+
                                             +--- strict mode ---> fallback_answer -> END

In hybrid mode (HYBRID_MODE=true) general_answer replies from the model's general
knowledge, clearly labelled and without citations; the service then files the answer
as a pending draft for an admin to review (see app/services/drafts.py).

grade_context combines cosine similarity (best chunk >= SIMILARITY_THRESHOLD, 0.25 by
default) with keyword overlap between the question and the retrieved text.
generate_answer must cite [doc_id]; missing citations are appended from the context.
All LLM calls go through the injected webhook function (app.services.llm_client).
"""
from __future__ import annotations

import logging
import re
from operator import add
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.services.knowledge_base import KnowledgeBase
from app.services.llm_client import LLMFn, LLMWebhookError

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = "I don't know based on the provided documentation."

ANSWER_SYSTEM_PROMPT = f"""You are the internal Knowledge Assistant for application development teams.
You answer like a senior software engineer: precise, practical and brief.

Rules:
1. Use ONLY the documentation context provided. Never use outside knowledge.
2. Cite every statement with the exact doc id in square brackets, e.g. [python-coding-standards].
   Only cite doc ids that appear in the context.
3. When the context contains a relevant code snippet, include it (or a minimal adaptation)
   in a fenced code block and cite it.
4. If the context does not answer the question, reply exactly: "{FALLBACK_MESSAGE}"
5. Answer in the same language as the question."""

REWRITE_SYSTEM_PROMPT = """You rewrite developer questions into search queries for an internal
technical documentation search engine (coding standards, runbooks, troubleshooting guides,
code snippets, issue tickets).
Return ONLY the rewritten query, in English, with the key technical terms and common synonyms.
No explanations, no quotes."""

GENERAL_SYSTEM_PROMPT = """You are a senior software engineer helping a colleague.
The company's internal documentation does not cover this question, so answer from widely
accepted, vendor-neutral engineering practice.

Rules:
1. Be correct, concise and practical; include a short code or command example when useful.
2. Do NOT invent company-specific facts (team names, internal URLs, policies, tickets, versions).
3. Do NOT use citations in square brackets: nothing here comes from internal documents.
4. If a team convention would normally decide the answer, say so in one sentence.
5. Answer in the same language as the question, formatted as Markdown with short headings."""

GENERAL_ANSWER_WARNING = (
    "Not found in the internal documentation: this is a general answer from the model. "
    "Verify it before applying it. It was sent to the admins for review."
)

STOP_WORDS = {
    # English
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "was",
    "were", "be", "can", "should", "do", "does", "did", "has", "have", "not", "what", "which", "who", "when", "where", "why",
    "how", "tell", "me", "about", "our", "we", "you", "my", "it", "this", "that", "use", "using",
    "there", "any", "get", "into", "from",
    # Spanish (developers may ask in Spanish against English docs)
    "que", "como", "para", "por", "los", "las", "una", "uno", "del", "con", "cual", "cuando",
    "donde", "nuestro", "nuestra", "debo", "hay", "esta", "este", "sobre",
}

# Used by the deterministic rewriter when the LLM webhook is unavailable.
QUERY_EXPANSIONS = {
    "error": "exception error handling troubleshooting",
    "slow": "latency performance timeout",
    "timeout": "timeout latency retry backoff",
    "db": "database connection pool",
    "database": "database connection pool sql",
    "deploy": "deployment release rollout pipeline",
    "rollback": "rollback deployment release revert",
    "log": "logging structured logs observability",
    "logs": "logging structured logs observability",
    "secret": "secrets credentials vault environment variables",
    "password": "secrets credentials vault",
    "branch": "git branching pull request merge",
    "commit": "git commit message conventional commits",
    "api": "rest api endpoint http status versioning",
    "retry": "retry exponential backoff idempotent",
    "test": "testing unit tests pytest coverage",
}

CITATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_.\-]*)\]")


class RAGState(TypedDict, total=False):
    original_question: str
    question: str
    attempts: int
    max_attempts: int
    top_k: int
    doc_type: str | None
    retrieved: list[dict]
    best_score: float
    keyword_overlap: list[str]
    context_is_relevant: bool
    answer: str
    status: str  # answered | general | no_answer | fallback | degraded
    citations: list[dict]
    llm_used: bool
    warnings: Annotated[list[str], add]
    trace: Annotated[list[str], add]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", text.lower())
    return {word for word in words if len(word) > 2 and word not in STOP_WORDS}


def format_context(docs: list[dict]) -> str:
    return "\n\n---\n\n".join(
        f'[{doc["doc_id"]}] {doc["title"]} > {doc["section"]} '
        f'(type={doc["doc_type"]}, similarity={doc["score"]:.2f})\n{doc["text"]}'
        for doc in docs
    )


def build_citations(docs: list[dict], doc_ids: list[str]) -> list[dict]:
    """One citation per doc_id, using its best-scoring chunk."""
    best: dict[str, dict] = {}
    for doc in docs:
        if doc["doc_id"] in doc_ids and (
            doc["doc_id"] not in best or doc["score"] > best[doc["doc_id"]]["score"]
        ):
            best[doc["doc_id"]] = doc
    return [
        {
            "doc_id": doc_id,
            "title": best[doc_id]["title"],
            "doc_type": best[doc_id]["doc_type"],
            "source_path": best[doc_id]["source_path"],
            "section": best[doc_id]["section"],
            "score": best[doc_id]["score"],
        }
        for doc_id in doc_ids
        if doc_id in best
    ]


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def heuristic_rewrite(question: str) -> str:
    expansions = [QUERY_EXPANSIONS[term] for term in keywords(question) if term in QUERY_EXPANSIONS]
    return " ".join([question, *expansions]).strip()


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_rag_graph(kb: KnowledgeBase, llm: LLMFn, settings: Settings):
    def initialize(state: RAGState) -> dict:
        question = state["question"].strip()
        max_attempts = state.get("max_attempts")
        return {
            "original_question": state.get("original_question", question),
            "question": question,
            "attempts": state.get("attempts", 0),
            "max_attempts": settings.max_attempts if max_attempts is None else max_attempts,
            "top_k": state.get("top_k") or settings.top_k,
            "doc_type": state.get("doc_type"),
            "llm_used": False,
            "trace": ["initialize"],
        }

    def retrieve(state: RAGState) -> dict:
        results = kb.search(state["question"], k=state["top_k"], doc_type=state.get("doc_type"))
        return {
            "retrieved": [result.to_dict() for result in results],
            "trace": [f'retrieve: "{state["question"]}" -> {len(results)} chunks'],
        }

    def grade_context(state: RAGState) -> dict:
        docs = state.get("retrieved", [])
        # Original + rewritten terms: a Spanish question rewritten in English must still match.
        question_terms = keywords(state["original_question"]) | keywords(state["question"])

        doc_terms: set[str] = set()
        for doc in docs:
            doc_terms |= keywords(f'{doc["title"]} {doc["section"]} {doc["text"]}')

        best_score = max((doc["score"] for doc in docs), default=0.0)
        overlap = sorted(question_terms & doc_terms)
        is_relevant = (
            best_score >= settings.similarity_threshold
            and len(overlap) >= settings.min_keyword_overlap
        )
        reason = f"best_score={best_score:.3f} (threshold {settings.similarity_threshold}), keyword_overlap={overlap[:8]}"
        return {
            "best_score": round(best_score, 4),
            "keyword_overlap": overlap,
            "context_is_relevant": is_relevant,
            "trace": [f"grade_context: {is_relevant} ({reason})"],
        }

    def route_after_grading(state: RAGState) -> str:
        if state["context_is_relevant"]:
            return "generate"
        if state["attempts"] < state["max_attempts"]:
            return "rewrite"
        return "fallback"

    def rewrite_question(state: RAGState) -> dict:
        attempts = state["attempts"] + 1
        prompt = (
            f"Original question: {state['original_question']}\n"
            f"Previous search query (returned weak results): {state['question']}\n"
            f"Attempt: {attempts}\n\nRewritten search query:"
        )
        warnings: list[str] = []
        try:
            rewritten = llm(prompt, REWRITE_SYSTEM_PROMPT).strip().strip('"').splitlines()[0][:300]
            source = "llm"
        except (LLMWebhookError, IndexError) as exc:
            rewritten = ""
            warnings.append(f"Query rewrite fell back to keyword expansion: {exc}")
            source = "heuristic"
        if not rewritten:
            rewritten = heuristic_rewrite(state["original_question"])
            source = "heuristic"

        return {
            "question": rewritten,
            "attempts": attempts,
            "warnings": warnings,
            "trace": [f'rewrite_question ({source}): attempt {attempts} -> "{rewritten}"'],
        }

    def generate_answer(state: RAGState) -> dict:
        docs = state["retrieved"]
        valid_ids = _unique([doc["doc_id"] for doc in docs])
        prompt = (
            f"Question:\n{state['original_question']}\n\n"
            f"Documentation context:\n{format_context(docs)}\n\n"
            "Answer citing doc ids in square brackets."
        )

        try:
            answer = llm(prompt, ANSWER_SYSTEM_PROMPT).strip()
        except LLMWebhookError as exc:
            # Degraded mode: still useful and still grounded - show the top excerpts.
            logger.warning("LLM webhook failed during generation: %s", exc)
            top = docs[:2]
            excerpts = "\n\n".join(f'[{doc["doc_id"]}] {doc["section"]}:\n{doc["text"]}' for doc in top)
            return {
                "answer": (
                    "The language model is unavailable, so here are the most relevant "
                    f"documentation excerpts:\n\n{excerpts}"
                ),
                "status": "degraded",
                "citations": build_citations(docs, _unique([doc["doc_id"] for doc in top])),
                "warnings": [f"LLM webhook error: {exc}"],
                "trace": ["generate_answer: degraded (LLM webhook unavailable)"],
            }

        if FALLBACK_MESSAGE.lower().rstrip(".") in answer.lower():
            return {
                "answer": FALLBACK_MESSAGE,
                "status": "no_answer",
                "citations": [],
                "llm_used": True,
                "trace": ["generate_answer: model declined (context insufficient)"],
            }

        cited = _unique([doc_id for doc_id in CITATION_RE.findall(answer) if doc_id in valid_ids])
        warnings: list[str] = []
        if not cited:
            # Mandatory citations: never return an unsourced answer.
            cited = valid_ids[:2]
            answer += "\n\nSources: " + ", ".join(f"[{doc_id}]" for doc_id in cited)
            warnings.append("The model omitted citations; sources were appended from the retrieved context.")

        return {
            "answer": answer,
            "status": "answered",
            "citations": build_citations(docs, cited),
            "llm_used": True,
            "warnings": warnings,
            "trace": [f"generate_answer: cited {cited}"],
        }

    def fallback_answer(state: RAGState) -> dict:
        return {
            "answer": FALLBACK_MESSAGE,
            "status": "fallback",
            "citations": [],
            "trace": [f"fallback_answer: context still weak after {state['attempts']} rewrite(s)"],
        }

    def general_answer(state: RAGState) -> dict:
        """Hybrid mode: answer from general knowledge, clearly labelled and never cited."""
        reason = (
            "documentation did not contain the answer"
            if state.get("status") == "no_answer"
            else f"context still weak after {state['attempts']} rewrite(s)"
        )
        try:
            answer = llm(f"Question:\n{state['original_question']}", GENERAL_SYSTEM_PROMPT).strip()
        except LLMWebhookError as exc:
            return {
                "answer": FALLBACK_MESSAGE,
                "status": "fallback",
                "citations": [],
                "warnings": [f"General answer unavailable (LLM webhook error: {exc})"],
                "trace": [f"general_answer: LLM webhook unavailable -> fallback ({reason})"],
            }
        return {
            "answer": answer,
            "status": "general",
            "citations": [],
            "llm_used": True,
            "warnings": [GENERAL_ANSWER_WARNING],
            "trace": [f"general_answer: {reason}; answered from general knowledge"],
        }

    def route_after_generation(state: RAGState) -> str:
        # The context looked relevant, but the model found no answer in it.
        if state["status"] == "no_answer" and settings.hybrid_mode:
            return "general"
        return "done"

    graph = StateGraph(RAGState)
    graph.add_node("initialize", initialize)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_context", grade_context)
    graph.add_node("rewrite_question", rewrite_question)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("fallback_answer", fallback_answer)
    graph.add_node("general_answer", general_answer)

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "retrieve")
    graph.add_edge("retrieve", "grade_context")
    graph.add_conditional_edges(
        "grade_context",
        route_after_grading,
        {
            "generate": "generate_answer",
            "rewrite": "rewrite_question",
            # Strict mode says "I don't know"; hybrid mode answers from general knowledge.
            "fallback": "general_answer" if settings.hybrid_mode else "fallback_answer",
        },
    )
    graph.add_edge("rewrite_question", "retrieve")
    graph.add_conditional_edges(
        "generate_answer",
        route_after_generation,
        {"general": "general_answer", "done": END},
    )
    graph.add_edge("fallback_answer", END)
    graph.add_edge("general_answer", END)

    return graph.compile()
