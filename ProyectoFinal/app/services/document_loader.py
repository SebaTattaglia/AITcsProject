"""
app/services/document_loader.py
Text extraction for the technical knowledge base:
Markdown/TXT, HTML, PDF, source-code snippets and JSON issue-tracking logs.

Every file becomes one or more Document objects with a stable doc_id, which is
the identifier the assistant must cite as [doc_id].
"""
from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".txt"}
HTML_EXTENSIONS = {".html", ".htm"}
CODE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".sql": "sql",
    ".sh": "bash",
    ".ps1": "powershell",
    ".yaml": "yaml",
    ".yml": "yaml",
}


@dataclass
class Document:
    doc_id: str
    title: str
    doc_type: str  # standard | guide | troubleshooting | runbook | snippet | issue | reference
    source_path: str
    text: str
    language: str | None = None
    tags: list[str] = field(default_factory=list)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _as_list(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Minimal YAML frontmatter parser (key: value and key: [a, b])."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            meta: dict[str, object] = {}
            for line in lines[1:end]:
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                value = value.strip()
                if value.startswith("[") and value.endswith("]"):
                    meta[key.strip()] = _as_list(value[1:-1].replace("'", "").replace('"', ""))
                else:
                    meta[key.strip()] = value.strip("'\"")
            return meta, "\n".join(lines[end + 1 :]).lstrip("\n")
    return {}, text


def _first_heading(text: str) -> str | None:
    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _humanize(stem: str) -> str:
    return re.sub(r"[_\-]+", " ", stem).strip().capitalize()


def _make_document(
    meta: dict[str, object],
    *,
    path: Path,
    rel: str,
    text: str,
    default_type: str,
    default_title: str | None = None,
    language: str | None = None,
) -> Document:
    return Document(
        doc_id=slugify(str(meta.get("doc_id") or path.stem)),
        title=str(meta.get("title") or default_title or _humanize(path.stem)),
        doc_type=str(meta.get("doc_type") or default_type).lower(),
        source_path=rel,
        text=text.strip(),
        language=str(meta.get("language") or language or "") or None,
        tags=_as_list(meta.get("tags")),
    )


# ---------------------------------------------------------------------------
# Loaders - one per format
# ---------------------------------------------------------------------------

def _load_markdown(path: Path, rel: str) -> list[Document]:
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8-sig"))
    return [
        _make_document(
            meta, path=path, rel=rel, text=body,
            default_type="guide", default_title=_first_heading(body),
        )
    ]


def _html_to_markdown(raw: str) -> tuple[dict[str, object], str | None, str]:
    soup = BeautifulSoup(raw, "html.parser")
    meta: dict[str, object] = {
        tag["name"]: tag.get("content", "") for tag in soup.find_all("meta") if tag.get("name")
    }
    title = soup.title.get_text(strip=True) if soup.title else None

    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    # Keep code blocks intact as fenced Markdown so the chunker never splits them.
    for pre in soup.find_all("pre"):
        code = pre.find("code")
        classes = (code.get("class") if code else None) or []
        lang = next((c.removeprefix("language-") for c in classes if c.startswith("language-")), "")
        pre.replace_with(f"\n\n```{lang}\n{pre.get_text().strip()}\n```\n\n")

    for level in range(1, 5):
        for heading in soup.find_all(f"h{level}"):
            heading.replace_with(f"\n\n{'#' * level} {heading.get_text(' ', strip=True)}\n\n")

    for item in soup.find_all("li"):
        item.insert(0, "- ")
    for block in soup.find_all(["p", "li", "tr", "div", "ul", "ol", "table"]):
        block.append("\n")

    body = soup.body or soup
    # Drop the HTML source indentation (so "  ## Heading" is a real heading),
    # but keep indentation inside fenced code blocks.
    lines, in_fence = [], False
    for line in body.get_text().splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            lines.append(line.strip())
        else:
            lines.append(line.rstrip() if in_fence else line.strip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return meta, title, text


def _load_html(path: Path, rel: str) -> list[Document]:
    meta, title, text = _html_to_markdown(path.read_text(encoding="utf-8-sig"))
    return [
        _make_document(
            meta, path=path, rel=rel, text=text,
            default_type="guide", default_title=title or _first_heading(text),
        )
    ]


def _load_pdf(path: Path, rel: str) -> list[Document]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    if not text.strip():
        logger.warning("PDF %s has no text layer (scanned?) - skipped", rel)
        return []
    pdf_title = reader.metadata.title if reader.metadata else None
    return [
        _make_document({}, path=path, rel=rel, text=text, default_type="reference", default_title=pdf_title)
    ]


def _code_description(code: str, suffix: str) -> str:
    if suffix == ".py":
        try:
            return ast.get_docstring(ast.parse(code)) or ""
        except SyntaxError:
            return ""
    # Leading comment block for other languages (#, //, --).
    lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", "//", "--")):
            lines.append(stripped.lstrip("#/- ").strip())
        elif stripped:
            break
    return "\n".join(lines)


def _load_code(path: Path, rel: str) -> list[Document]:
    code = path.read_text(encoding="utf-8-sig")
    language = CODE_EXTENSIONS[path.suffix.lower()]
    description = _code_description(code, path.suffix.lower())
    title = (description.splitlines()[0].rstrip(".") if description else None) or _humanize(path.stem)
    text = f"# {title}\n\n{description}\n\nFile: {path.name}\n\n```{language}\n{code.strip()}\n```"
    return [
        _make_document(
            {}, path=path, rel=rel, text=text,
            default_type="snippet", default_title=title, language=language,
        )
    ]


def _load_issue_log(path: Path, rel: str) -> list[Document]:
    """A JSON list of tickets; each ticket becomes its own citable document."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not all(isinstance(i, dict) and "key" in i for i in data):
        logger.warning("JSON %s is not an issue log (list of objects with 'key') - skipped", rel)
        return []

    documents = []
    for issue in data:
        key = str(issue["key"])
        sections = [f"# {key}: {issue.get('summary', '')}"]
        details = [
            ("Component", issue.get("component")),
            ("Status", issue.get("status")),
            ("Priority", issue.get("priority")),
            ("Environment", issue.get("environment")),
        ]
        sections.append("\n".join(f"**{label}:** {value}" for label, value in details if value))
        for label, field_name in [
            ("Symptoms", "symptoms"),
            ("Root cause", "root_cause"),
            ("Resolution", "resolution"),
        ]:
            if issue.get(field_name):
                sections.append(f"## {label}\n{issue[field_name]}")
        documents.append(
            Document(
                doc_id=slugify(key),
                title=f"{key}: {issue.get('summary', '')}".strip(),
                doc_type="issue",
                source_path=f"{rel}#{key}",
                text="\n\n".join(sections),
                tags=_as_list(issue.get("labels")),
            )
        )
    return documents


def load_documents(docs_dir: Path) -> list[Document]:
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"Documentation folder not found: {docs_dir}")

    documents: list[Document] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(docs_dir).parts):
            continue
        rel = path.relative_to(docs_dir).as_posix()
        suffix = path.suffix.lower()
        try:
            if suffix in MARKDOWN_EXTENSIONS:
                documents.extend(_load_markdown(path, rel))
            elif suffix in HTML_EXTENSIONS:
                documents.extend(_load_html(path, rel))
            elif suffix == ".pdf":
                documents.extend(_load_pdf(path, rel))
            elif suffix in CODE_EXTENSIONS:
                documents.extend(_load_code(path, rel))
            elif suffix == ".json":
                documents.extend(_load_issue_log(path, rel))
        except Exception:  # one broken file must not take the whole index down
            logger.exception("Could not load %s - skipped", rel)

    seen: dict[str, str] = {}
    for doc in documents:
        if doc.doc_id in seen:
            raise ValueError(
                f"Duplicate doc_id '{doc.doc_id}' in {doc.source_path} and {seen[doc.doc_id]}. "
                "Set a unique doc_id in the frontmatter."
            )
        seen[doc.doc_id] = doc.source_path
    return documents
