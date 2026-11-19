'''MCP server: the Dev Knowledge Assistant inside developer IDEs (VS Code, Cursor, Claude Code).

Exposes tools, resources and prompts over the stdio transport (Lesson 8).
It reuses AssistantService in-process, so answers are identical to the REST API.

Run it directly for a syntax check:  python mcp_server/server.py
(it will block, waiting for a host to speak first — that is correct)
'''

import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

# The IDE launches this file by absolute path; make the `app` package importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server import MCPServer  # noqa: E402

from app.services.assistant_service import get_assistant_service  # noqa: E402

# stdout is the MCP channel: logs must go to stderr.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)

mcp = MCPServer(
    'Dev Knowledge Assistant',
    instructions=(
        'Internal knowledge assistant for application development teams. '
        'Use ask_dev_assistant for questions about coding standards, APIs, deployments, '
        'troubleshooting and past incidents; answers cite sources as [doc_id]. '
        'Use search_code_snippets to find reusable code before writing it from scratch.'
    ),
)


def _service():
    # Lazy: the index is built on the first tool call, so the IDE handshake stays fast.
    return get_assistant_service()


def _compact(results: list[dict], max_chars: int = 1200) -> list[dict[str, Any]]:
    return [
        {
            'doc_id': r['doc_id'],
            'title': r['title'],
            'section': r['section'],
            'doc_type': r['doc_type'],
            'source_path': r['source_path'],
            'score': r['score'],
            'text': r['text'][:max_chars],
        }
        for r in results
    ]


# ---------------------------------------------------------------------------
# Tools — the model can request these
# ---------------------------------------------------------------------------

@mcp.tool()
def ask_dev_assistant(question: str, max_attempts: int = 2) -> dict[str, Any]:
    '''Answer a technical question from the internal documentation (coding standards,
    REST API guidelines, runbooks, troubleshooting guides, issue tickets, code snippets).
    The answer cites its sources as [doc_id]. status="general" means the docs do not cover it and the
    answer comes from general knowledge (verify it; it was queued for admin review).
    status="fallback" means no answer could be produced.'''
    if not question.strip():
        return {'error': 'The question is empty. Ask the user what they need to know.'}
    result = _service().ask(question, max_attempts=max(0, min(max_attempts, 5)))
    return {
        'answer': result['answer'],
        'status': result['status'],
        'citations': result['citations'],
        'attempts': result['attempts'],
        'warnings': result['warnings'],
        'draft_id': result['draft_id'],
    }


@mcp.tool()
def search_documentation(query: str, k: int = 5, doc_type: str | None = None) -> dict[str, Any]:
    '''Semantic search over the internal documentation without generating an answer.
    doc_type (optional): standard, guide, troubleshooting, runbook, snippet, issue, reference.'''
    results = _service().search(query, k=max(1, min(k, 20)), doc_type=doc_type)
    return {'query': query, 'results': _compact(results)}


@mcp.tool()
def search_code_snippets(query: str, language: str | None = None, k: int = 3) -> dict[str, Any]:
    '''Find approved, reusable code snippets (e.g. retry with backoff, DB session handling,
    pagination, structured logging). language (optional): python, javascript, sql, ...'''
    results = _service().search_snippets(query, language=language, k=max(1, min(k, 10)))
    if not results:
        return {'query': query, 'results': [], 'error': 'No snippets found for that query/language.'}
    return {'query': query, 'results': _compact(results, max_chars=4000)}


@mcp.tool()
def get_document(doc_id: str) -> dict[str, Any]:
    '''Return the full text of one document by its doc_id (the id used in citations).'''
    doc = _service().get_document(doc_id)
    if doc is None:
        return {'found': False, 'doc_id': doc_id, 'error': 'Document not found. Use list_documents to see valid ids.'}
    return {'found': True, **asdict(doc)}


@mcp.tool()
def list_documents(doc_type: str | None = None) -> list[dict[str, Any]]:
    '''List the documents in the knowledge base (doc_id, title, type), optionally filtered by doc_type.'''
    return [
        {'doc_id': d.doc_id, 'title': d.title, 'doc_type': d.doc_type, 'language': d.language}
        for d in _service().list_documents(doc_type)
    ]


# ---------------------------------------------------------------------------
# Resources — the application can read these (no model involved)
# ---------------------------------------------------------------------------

@mcp.resource('devkb://catalog')
def catalog() -> str:
    '''Catalogue of every document in the knowledge base, grouped by type.'''
    lines = []
    for doc in sorted(_service().list_documents(), key=lambda d: (d.doc_type, d.doc_id)):
        lines.append(f'[{doc.doc_type}] {doc.doc_id} - {doc.title}')
    return '\n'.join(lines)


@mcp.resource('devkb://docs/{doc_id}')
def document_resource(doc_id: str) -> str:
    '''Full text of one document.'''
    doc = _service().get_document(doc_id)
    return doc.text if doc else f'Document "{doc_id}" not found.'


# ---------------------------------------------------------------------------
# Prompts — the user can pick these
# ---------------------------------------------------------------------------

@mcp.prompt()
def review_against_standards(code: str, language: str = 'python') -> str:
    '''Review a piece of code against the team coding standards.'''
    return (
        f'Review the following {language} code against our internal coding standards. '
        'First call ask_dev_assistant / search_documentation to retrieve the relevant standards, '
        'then list each violation with the rule it breaks and its [doc_id], and propose a fix.\n\n'
        f'```{language}\n{code}\n```'
    )


@mcp.prompt()
def troubleshoot_error(error_message: str, service_name: str = '') -> str:
    '''Diagnose an error using the troubleshooting guides and past issue tickets.'''
    where = f' in the service "{service_name}"' if service_name else ''
    return (
        f'We are seeing this error{where}:\n\n{error_message}\n\n'
        'Search the troubleshooting guides and issue tickets (doc_type=issue) for similar cases, '
        'then give the most likely root cause and the resolution steps, citing [doc_id].'
    )


if __name__ == '__main__':
    # No arguments means stdio: the host launches this file as a subprocess.
    mcp.run()
