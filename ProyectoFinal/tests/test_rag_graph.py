from app.services.assistant_service import AssistantService
from app.services.embeddings import TfidfEmbedder
from app.services.rag_graph import FALLBACK_MESSAGE

from tests.conftest import FakeLLM


def make_service(settings, llm: FakeLLM) -> AssistantService:
    return AssistantService(settings, llm=llm, embedder_factory=TfidfEmbedder)


def test_relevant_question_is_answered_with_citations(service):
    result = service.ask("How do I roll back a bad deployment?")

    assert result["status"] == "answered"
    assert result["attempts"] == 0
    assert result["best_score"] >= 0.25
    assert "[deployment-runbook]" in result["answer"]
    assert result["citations"][0]["doc_id"] == "deployment-runbook"
    assert result["trace"][0] == "initialize"


def test_weak_context_triggers_rewrite_loop(settings):
    llm = FakeLLM(rewrite="git commit message conventional commits format")
    result = make_service(settings, llm).ask("What is the commit message format?")

    assert result["attempts"] == 1
    assert any(step.startswith("rewrite_question (llm)") for step in result["trace"])
    assert result["status"] == "answered"
    assert result["citations"][0]["doc_id"] == "git-workflow"


def test_rewrite_falls_back_to_keyword_expansion_when_llm_fails(settings):
    llm = FakeLLM(rewrite=None)  # rewrite call raises LLMWebhookError
    result = make_service(settings, llm).ask("What is the commit message format?")

    assert any(step.startswith("rewrite_question (heuristic)") for step in result["trace"])
    assert any("keyword expansion" in w for w in result["warnings"])


def test_out_of_scope_question_ends_in_fallback(service, fake_llm):
    result = service.ask("What is the capital city of Mars?", max_attempts=2)

    assert result["status"] == "fallback"
    assert result["answer"] == FALLBACK_MESSAGE
    assert result["attempts"] == 2
    assert result["citations"] == []
    assert not any(system for _, system in fake_llm.calls if "Knowledge Assistant" in system)


def test_missing_citations_are_appended(settings):
    result = make_service(settings, FakeLLM(cite=False)).ask("How do I roll back a bad deployment?")

    assert result["status"] == "answered"
    assert "Sources: [deployment-runbook]" in result["answer"]
    assert any("omitted citations" in w for w in result["warnings"])


def test_llm_outage_returns_grounded_excerpts(settings):
    result = make_service(settings, FakeLLM(fail=True)).ask("How do I roll back a bad deployment?")

    assert result["status"] == "degraded"
    assert "[deployment-runbook]" in result["answer"]
    assert result["citations"]
    assert result["llm_used"] is False


def test_snippet_search_filters_by_type_and_language(service):
    results = service.search_snippets("retry with exponential backoff", language="python", k=2)

    assert results[0]["doc_id"] == "retry-with-backoff"
    assert all(r["doc_type"] == "snippet" for r in results)
