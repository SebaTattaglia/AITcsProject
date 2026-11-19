from tests.conftest import ADMIN_KEY, DEV_KEY

DEV = {"X-API-Key": DEV_KEY}
ADMIN = {"X-API-Key": ADMIN_KEY}


def test_health_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["index"]["documents"] > 0


def test_missing_and_invalid_keys_are_rejected(client):
    assert client.post("/api/v1/assistant/ask", json={"question": "rollback"}).status_code == 401
    assert client.post("/api/v1/assistant/ask", json={"question": "rollback"}, headers={"X-API-Key": "nope"}).status_code == 401


def test_ask_returns_answer_with_citations(client):
    response = client.post("/api/v1/assistant/ask", json={"question": "How do I roll back a bad deployment?"}, headers=DEV)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["citations"][0]["doc_id"] == "deployment-runbook"


def test_ask_validates_payload(client):
    assert client.post("/api/v1/assistant/ask", json={"question": "x"}, headers=DEV).status_code == 422
    assert client.post("/api/v1/assistant/ask", json={"question": "valid question", "max_attempts": 9}, headers=DEV).status_code == 422


def test_search_and_snippets(client):
    search = client.post("/api/v1/search", json={"query": "duplicate payments idempotency", "k": 2}, headers=DEV)
    snippets = client.get("/api/v1/snippets/search", params={"q": "cursor pagination", "language": "python"}, headers=DEV)

    assert search.status_code == 200
    assert search.json()["results"][0]["doc_id"] == "dev-1150"
    assert snippets.json()["results"][0]["doc_id"] == "fastapi-pagination"


def test_documents_endpoints(client):
    listing = client.get("/api/v1/documents", params={"doc_type": "issue"}, headers=DEV)
    detail = client.get("/api/v1/documents/git-workflow", headers=DEV)

    assert {d["doc_type"] for d in listing.json()} == {"issue"}
    assert "Conventional Commits" in detail.json()["text"]
    assert client.get("/api/v1/documents/does-not-exist", headers=DEV).status_code == 404


def test_reindex_requires_admin_role(client):
    assert client.post("/api/v1/admin/reindex", headers=DEV).status_code == 403

    response = client.post("/api/v1/admin/reindex", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["chunks"] > 0


def test_ui_is_served_at_root(client):
    root = client.get("/", follow_redirects=False)
    page = client.get("/ui/")

    assert root.status_code == 307 and root.headers["location"] == "/ui/"
    assert page.status_code == 200
    assert "Dev Knowledge Assistant" in page.text
    assert client.get("/ui/app.js").status_code == 200
