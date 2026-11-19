from app.core.config import PROJECT_ROOT
from app.services.chunker import TokenCounter, chunk_document, split_blocks
from app.services.document_loader import Document, load_documents

DOCS_DIR = PROJECT_ROOT / "data" / "docs"


def test_loads_every_supported_format():
    docs = {doc.doc_id: doc for doc in load_documents(DOCS_DIR)}

    assert docs["python-coding-standards"].doc_type == "standard"            # Markdown + frontmatter
    assert docs["deployment-runbook"].doc_type == "runbook"                  # HTML <meta>
    assert "```bash" in docs["deployment-runbook"].text                      # <pre><code> kept as a fence
    assert docs["retry-with-backoff"].doc_type == "snippet"                  # source code
    assert docs["retry-with-backoff"].language == "python"
    assert docs["dev-1042"].doc_type == "issue"                              # JSON issue log, one doc per ticket
    assert "QueuePool" in docs["dev-1042"].text


def test_code_fences_are_never_split():
    text = "## Example\n\nIntro line.\n\n```python\na = 1\n\nb = 2\n```\n\nAfter."
    blocks = split_blocks(text)

    assert [section for section, _ in blocks] == ["Example"] * 3
    assert blocks[1][1] == "```python\na = 1\n\nb = 2\n```"


def test_chunks_respect_token_budget_and_sections():
    counter = TokenCounter()
    body = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(12))
    doc = Document(doc_id="demo", title="Demo", doc_type="guide", source_path="demo.md",
                   text=f"# Demo\n\n## First\n\n{body}\n\n## Second\n\nShort.")

    chunks = chunk_document(doc, counter, max_tokens=120, overlap_tokens=60)

    assert all(c.token_count <= 120 for c in chunks)
    assert {c.section for c in chunks} == {"First", "Second"}
    assert chunks[0].chunk_id == "demo#0"
    assert chunks[-1].section == "Second"


def test_oversized_code_block_is_refenced():
    counter = TokenCounter()
    code = "\n".join(f"value_{i} = compute({i})" for i in range(200))
    doc = Document(doc_id="big", title="Big", doc_type="snippet", source_path="big.py",
                   text=f"```python\n{code}\n```")

    chunks = chunk_document(doc, counter, max_tokens=150, overlap_tokens=0)

    assert len(chunks) > 1
    assert all(c.text.startswith("```python") and c.text.endswith("```") for c in chunks)


def test_html_headings_become_sections():
    runbook = next(d for d in load_documents(DOCS_DIR) if d.doc_id == "deployment-runbook")
    sections = {c.section for c in chunk_document(runbook, TokenCounter())}

    assert {"Rollback procedure", "Database migrations"} <= sections
