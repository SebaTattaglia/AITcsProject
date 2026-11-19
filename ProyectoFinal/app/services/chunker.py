"""
app/services/chunker.py
Section-aware chunking measured in BPE tokens (tiktoken), as in Lesson 3.

Rules:
- A chunk never mixes two sections, so a citation points to one coherent place.
- Fenced code blocks are never cut in half (oversized ones are re-fenced per piece).
- Consecutive chunks of a section share a small overlap block.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import tiktoken

from app.services.document_loader import Document

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)(.*)$")
DEFAULT_SECTION = "Overview"


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    doc_type: str
    source_path: str
    section: str
    text: str
    token_count: int
    language: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def embedding_text(self) -> str:
        # Title, section and tags carry most of the keywords a developer will type.
        return f"{self.title}\n{self.section}\n{' '.join(self.tags)}\n{self.text}"


class TokenCounter:
    """tiktoken counter (o200k_base = gpt-4.1 family) with an offline approximation."""

    def __init__(self, encoding_name: str = "o200k_base") -> None:
        try:
            self._encoding = tiktoken.get_encoding(encoding_name)
        except Exception as exc:  # the BPE file is downloaded on first use
            logger.warning("tiktoken unavailable (%s); using a word-based estimate", exc)
            self._encoding = None

    def count(self, text: str) -> int:
        if self._encoding is not None:
            return len(self._encoding.encode(text, disallowed_special=()))
        return max(1, round(len(text.split()) * 1.3))


def split_blocks(text: str) -> list[tuple[str, str]]:
    """Split Markdown into (section_path, block) pairs; blocks are paragraphs or code fences."""
    blocks: list[tuple[str, str]] = []
    headings: list[tuple[int, str]] = []
    current: list[str] = []
    in_fence = False

    def section() -> str:
        return " > ".join(title for _, title in headings) or DEFAULT_SECTION

    def flush() -> None:
        if current and "\n".join(current).strip():
            blocks.append((section(), "\n".join(current).strip()))
        current.clear()

    for line in text.splitlines():
        if FENCE_RE.match(line):
            if not in_fence:
                flush()
                in_fence = True
                current.append(line)
            else:
                current.append(line)
                in_fence = False
                flush()
            continue

        if in_fence:
            current.append(line)
            continue

        heading = HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            if level > 1:  # H1 is the document title, already stored on the chunk
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, heading.group(2).strip()))
            continue

        if not line.strip():
            flush()
            continue

        current.append(line)

    flush()
    return blocks


def _split_oversized(block: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    lines = block.splitlines()
    fence = FENCE_RE.match(lines[0]) if lines else None
    is_code = bool(fence) and len(lines) > 1 and FENCE_RE.match(lines[-1]) is not None
    opening, closing = (lines[0], lines[-1]) if is_code else ("", "")
    body = lines[1:-1] if is_code else lines

    pieces: list[str] = []
    current: list[str] = []
    for line in body:
        candidate = "\n".join(current + [line])
        if current and counter.count(candidate) > max_tokens:
            pieces.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        pieces.append("\n".join(current))

    if is_code:
        return [f"{opening}\n{piece}\n{closing}" for piece in pieces]
    return pieces


def chunk_document(
    doc: Document,
    counter: TokenCounter,
    max_tokens: int = 350,
    overlap_tokens: int = 60,
) -> list[Chunk]:
    # Group consecutive blocks by section, preserving document order.
    grouped: list[tuple[str, list[str]]] = []
    for section, block in split_blocks(doc.text):
        if grouped and grouped[-1][0] == section:
            grouped[-1][1].append(block)
        else:
            grouped.append((section, [block]))

    chunks: list[Chunk] = []

    def emit(section: str, pieces: list[str]) -> None:
        text = "\n\n".join(pieces)
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}#{len(chunks)}",
                doc_id=doc.doc_id,
                title=doc.title,
                doc_type=doc.doc_type,
                source_path=doc.source_path,
                section=section,
                text=text,
                token_count=counter.count(text),
                language=doc.language,
                tags=doc.tags,
            )
        )

    for section, blocks in grouped:
        pieces: list[str] = []
        for block in blocks:
            if counter.count(block) > max_tokens:
                pieces.extend(_split_oversized(block, counter, max_tokens))
            else:
                pieces.append(block)

        current: list[str] = []
        current_tokens = 0
        for piece in pieces:
            tokens = counter.count(piece)
            if current and current_tokens + tokens > max_tokens:
                emit(section, current)
                last = current[-1]
                last_tokens = counter.count(last)
                keep_overlap = last_tokens <= overlap_tokens and last_tokens + tokens <= max_tokens
                current = [last] if keep_overlap else []
                current_tokens = last_tokens if keep_overlap else 0
            current.append(piece)
            current_tokens += tokens
        if current:
            emit(section, current)

    return chunks
