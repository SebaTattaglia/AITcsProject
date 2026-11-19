"""
app/services/drafts.py
Review queue for knowledge gaps (same idea as the Incident2KB pending -> approved flow).

When the documentation cannot answer a question, the hybrid graph answers from the
model's general knowledge and the answer is stored here as a *pending draft*.
Nothing reaches the knowledge base until an admin approves it; approval writes a
Markdown document into data/docs/approved/ and the index is rebuilt.

Similar questions bump the same pending draft (asked_count), so the queue doubles
as a ranked list of what the documentation is missing.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.services.document_loader import slugify
from app.services.rag_graph import keywords

SIMILARITY_TO_MERGE = 0.6  # keyword Jaccard between two questions
MAX_QUESTIONS_KEPT = 10


class DraftNotFoundError(KeyError):
    pass


class DraftConflictError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _single_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def propose_title(question: str) -> str:
    title = _single_line(question).rstrip("?¿!. ").lstrip("¿¡")
    return (title[:1].upper() + title[1:])[:90] or "Untitled"


class DraftStore:
    """JSON-file store; small, human-readable and easy to back up with the docs."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / "drafts.json"
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _save(self, drafts: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash never leaves a half-written file.
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(drafts, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, self._path)

    # -- queries -------------------------------------------------------------

    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            drafts = self._load()
        if status:
            drafts = [d for d in drafts if d["status"] == status]
        # Most-asked first: the top of the queue is the biggest documentation gap.
        return sorted(drafts, key=lambda d: (-d["asked_count"], d["created_at"]))

    def get(self, draft_id: str) -> dict:
        with self._lock:
            for draft in self._load():
                if draft["id"] == draft_id:
                    return draft
        raise DraftNotFoundError(draft_id)

    def counts(self) -> dict[str, int]:
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for draft in self.list():
            counts[draft["status"]] = counts.get(draft["status"], 0) + 1
        return counts

    # -- commands ------------------------------------------------------------

    def record(self, question: str, answer: str) -> dict:
        """Create a pending draft, or bump the pending draft of a similar question."""
        question = _single_line(question)
        terms = keywords(question)
        with self._lock:
            drafts = self._load()
            for draft in drafts:
                if draft["status"] != "pending":
                    continue
                same = draft["question"].lower() == question.lower()
                if same or _jaccard(terms, keywords(" ".join(draft["questions"]))) >= SIMILARITY_TO_MERGE:
                    draft["asked_count"] += 1
                    if question not in draft["questions"]:
                        draft["questions"] = (draft["questions"] + [question])[-MAX_QUESTIONS_KEPT:]
                    draft["updated_at"] = _now()
                    self._save(drafts)
                    return draft

            title = propose_title(question)
            draft = {
                "id": uuid.uuid4().hex[:10],
                "status": "pending",
                "question": question,
                "questions": [question],
                "asked_count": 1,
                "title": title,
                "doc_id": slugify(title)[:60],
                "doc_type": "guide",
                "tags": sorted(terms)[:6],
                "content": answer.strip(),
                "created_at": _now(),
                "updated_at": _now(),
                "reviewed_by": None,
                "reviewed_at": None,
                "review_note": None,
                "published_path": None,
            }
            drafts.append(draft)
            self._save(drafts)
            return draft

    def update(self, draft_id: str, **changes) -> dict:
        allowed = {"title", "doc_id", "doc_type", "tags", "content"}
        with self._lock:
            drafts = self._load()
            draft = next((d for d in drafts if d["id"] == draft_id), None)
            if draft is None:
                raise DraftNotFoundError(draft_id)
            if draft["status"] != "pending":
                raise DraftConflictError(f"Draft is already {draft['status']}")
            for key, value in changes.items():
                if key in allowed and value is not None:
                    draft[key] = slugify(value) if key == "doc_id" else value
            draft["updated_at"] = _now()
            self._save(drafts)
            return draft

    def close(self, draft_id: str, status: str, reviewer: str, note: str | None = None,
              published_path: str | None = None) -> dict:
        with self._lock:
            drafts = self._load()
            draft = next((d for d in drafts if d["id"] == draft_id), None)
            if draft is None:
                raise DraftNotFoundError(draft_id)
            if draft["status"] != "pending":
                raise DraftConflictError(f"Draft is already {draft['status']}")
            draft.update(
                status=status,
                reviewed_by=reviewer,
                reviewed_at=_now(),
                review_note=note,
                published_path=published_path,
                updated_at=_now(),
            )
            self._save(drafts)
            return draft


def render_document(draft: dict, reviewer: str) -> str:
    """Markdown with frontmatter, in the same format as the hand-written docs."""
    tags = ", ".join(draft.get("tags") or [])
    question = _single_line(draft["question"]).replace('"', "'")
    return (
        "---\n"
        f"doc_id: {draft['doc_id']}\n"
        f"title: {_single_line(draft['title'])}\n"
        f"doc_type: {draft['doc_type']}\n"
        f"tags: [{tags}]\n"
        f"source: approved-draft-{draft['id']}\n"
        f"source_question: {question}\n"
        f"approved_by: {reviewer}\n"
        f"approved_at: {_now()}\n"
        "---\n\n"
        f"# {_single_line(draft['title'])}\n\n"
        f"{draft['content'].strip()}\n"
    )
