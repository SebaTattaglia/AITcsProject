import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.assistant_service import AssistantService, get_assistant_service
from app.services.drafts import DraftConflictError
from app.services.embeddings import TfidfEmbedder
from app.services.rag_graph import FALLBACK_MESSAGE

from tests.conftest import ADMIN_KEY, DEV_KEY, FakeLLM

DEV = {"X-API-Key": DEV_KEY}
ADMIN = {"X-API-Key": ADMIN_KEY}
OUT_OF_SCOPE = "What is the capital city of Mars?"


@pytest.fixture
def hybrid_settings(settings):
    return dataclasses.replace(settings, hybrid_mode=True)


def make_service(settings, llm=None) -> AssistantService:
    return AssistantService(settings, llm=llm or FakeLLM(), embedder_factory=TfidfEmbedder)


@pytest.fixture
def hybrid_service(hybrid_settings):
    return make_service(hybrid_settings)


@pytest.fixture
def hybrid_client(hybrid_settings, hybrid_service):
    app.dependency_overrides[get_settings] = lambda: hybrid_settings
    app.dependency_overrides[get_assistant_service] = lambda: hybrid_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Graph / service -------------------------------------------------------

def test_weak_context_gets_general_answer_and_a_draft(hybrid_service):
    result = hybrid_service.ask(OUT_OF_SCOPE, max_attempts=1)

    assert result["status"] == "general"
    assert result["citations"] == []
    assert "git revert" in result["answer"]
    assert any("Not found in the internal documentation" in w for w in result["warnings"])
    assert result["trace"][-1].startswith("general_answer")
    assert hybrid_service.get_draft(result["draft_id"])["status"] == "pending"


def test_model_decline_on_relevant_context_also_goes_hybrid(hybrid_settings):
    service = make_service(hybrid_settings, FakeLLM(decline=True))
    result = service.ask("How do I roll back a bad deployment?")

    assert any(step.startswith("generate_answer: model declined") for step in result["trace"])
    assert result["status"] == "general"
    assert result["draft_id"]


def test_strict_mode_keeps_i_dont_know(service):
    result = service.ask(OUT_OF_SCOPE, max_attempts=1)

    assert result["status"] == "fallback"
    assert result["answer"] == FALLBACK_MESSAGE
    assert result["draft_id"] is None


def test_general_answer_degrades_to_fallback_when_webhook_is_down(hybrid_settings):
    result = make_service(hybrid_settings, FakeLLM(fail=True)).ask(OUT_OF_SCOPE, max_attempts=0)

    assert result["status"] == "fallback"
    assert result["draft_id"] is None


def test_similar_questions_bump_the_same_draft(hybrid_service):
    first = hybrid_service.ask("How do I center a div with flexbox?", max_attempts=0)
    second = hybrid_service.ask("how to center a div using flexbox", max_attempts=0)

    assert first["draft_id"] == second["draft_id"]
    draft = hybrid_service.get_draft(first["draft_id"])
    assert draft["asked_count"] == 2
    assert len(draft["questions"]) == 2


def test_approved_draft_becomes_a_cited_document(hybrid_service, hybrid_settings):
    question = "How do I center a div with flexbox?"
    draft_id = hybrid_service.ask(question, max_attempts=0)["draft_id"]

    draft, stats = hybrid_service.approve_draft(
        draft_id, "admin:test", doc_id="css-flexbox-centering", title="Centering a div with flexbox",
        content="Use `display: flex; justify-content: center; align-items: center;` on the parent.",
    )

    assert draft["status"] == "approved"
    assert (hybrid_settings.docs_dir / "approved" / "css-flexbox-centering.md").exists()
    assert hybrid_service.get_document("css-flexbox-centering").title == "Centering a div with flexbox"
    assert stats["pending_drafts"] == 0
    answer = hybrid_service.ask(question)
    assert answer["status"] == "answered"
    assert answer["draft_id"] is None
    assert answer["citations"][0]["doc_id"] == "css-flexbox-centering"


def test_cannot_publish_over_an_existing_doc_id(hybrid_service):
    draft_id = hybrid_service.ask(OUT_OF_SCOPE, max_attempts=0)["draft_id"]

    with pytest.raises(DraftConflictError):
        hybrid_service.approve_draft(draft_id, "admin:test", doc_id="git-workflow")


# --- API -------------------------------------------------------------------

def test_admin_endpoints_require_admin_role(hybrid_client):
    assert hybrid_client.get("/api/v1/admin/drafts", headers=DEV).status_code == 403
    assert hybrid_client.get("/api/v1/admin/drafts", headers=ADMIN).status_code == 200
    assert hybrid_client.get("/api/v1/me", headers=ADMIN).json()["role"] == "admin"


def test_review_flow_over_http(hybrid_client):
    ask = hybrid_client.post("/api/v1/assistant/ask", json={"question": OUT_OF_SCOPE, "max_attempts": 0}, headers=DEV)
    draft_id = ask.json()["draft_id"]
    assert ask.json()["status"] == "general"

    pending = hybrid_client.get("/api/v1/admin/drafts", params={"status": "pending"}, headers=ADMIN).json()
    assert [d["id"] for d in pending] == [draft_id]

    bad = hybrid_client.patch(f"/api/v1/admin/drafts/{draft_id}", json={"doc_id": "Not Valid!"}, headers=ADMIN)
    assert bad.status_code == 422

    edited = hybrid_client.patch(f"/api/v1/admin/drafts/{draft_id}", json={"doc_id": "mars-facts"}, headers=ADMIN)
    assert edited.json()["doc_id"] == "mars-facts"

    approved = hybrid_client.post(f"/api/v1/admin/drafts/{draft_id}/approve", headers=ADMIN)
    assert approved.status_code == 200
    assert approved.json()["draft"]["published_path"] == "approved/mars-facts.md"
    assert hybrid_client.get("/api/v1/documents/mars-facts", headers=DEV).status_code == 200

    again = hybrid_client.post(f"/api/v1/admin/drafts/{draft_id}/approve", headers=ADMIN)
    assert again.status_code == 409


def test_reject_over_http(hybrid_client):
    draft_id = hybrid_client.post(
        "/api/v1/assistant/ask", json={"question": OUT_OF_SCOPE, "max_attempts": 0}, headers=DEV
    ).json()["draft_id"]

    rejected = hybrid_client.post(f"/api/v1/admin/drafts/{draft_id}/reject", json={"note": "Off-topic"}, headers=ADMIN)

    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["review_note"] == "Off-topic"
    assert hybrid_client.get("/api/v1/admin/drafts/nope", headers=ADMIN).status_code == 404
