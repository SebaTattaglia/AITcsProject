"""
Shared fixtures: an offline service (TF-IDF embeddings + fake LLM webhook),
so the suite never needs network access or credentials.
"""
from __future__ import annotations

import dataclasses
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.main import app
from app.services.assistant_service import AssistantService, get_assistant_service
from app.services.embeddings import TfidfEmbedder
from app.services.llm_client import LLMWebhookError
from app.services.rag_graph import ANSWER_SYSTEM_PROMPT, FALLBACK_MESSAGE, GENERAL_SYSTEM_PROMPT

DEV_KEY = "test-dev-key"
ADMIN_KEY = "test-admin-key"


class FakeLLM:
    """Stands in for the webhook. Answers cite the first doc id found in the context."""

    def __init__(self, fail: bool = False, cite: bool = True, rewrite: str | None = None,
                 decline: bool = False) -> None:
        self.fail = fail
        self.cite = cite
        self.rewrite = rewrite
        self.decline = decline  # model says the docs do not contain the answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt: str, system: str) -> str:
        self.calls.append((prompt, system))
        if self.fail:
            raise LLMWebhookError("HTTP 503: gateway unavailable")
        if system == GENERAL_SYSTEM_PROMPT:
            return "Use `git revert <sha>` to create a new commit that undoes the change."
        if system != ANSWER_SYSTEM_PROMPT:
            if self.rewrite is None:
                raise LLMWebhookError("rewrite not configured")
            return self.rewrite
        if self.decline:
            return FALLBACK_MESSAGE
        doc_id = re.search(r"^\[([^\]]+)\]", prompt.split("Documentation context:\n", 1)[1], re.M).group(1)
        return f"Use the documented approach [{doc_id}]." if self.cite else "Use the documented approach."


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Work on a copy of the docs: approving a draft writes into docs_dir.
    docs_dir = tmp_path / "docs"
    shutil.copytree(PROJECT_ROOT / "data" / "docs", docs_dir, ignore=shutil.ignore_patterns("approved"))
    return dataclasses.replace(
        Settings.from_env(),
        n8n_webhook_url="",
        docs_dir=docs_dir,
        index_dir=tmp_path / "index",
        drafts_dir=tmp_path / "drafts",
        hybrid_mode=False,
        similarity_threshold=0.25,
        min_keyword_overlap=1,
        max_attempts=2,
        top_k=4,
        api_keys={DEV_KEY: "developer", ADMIN_KEY: "admin"},
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def service(settings, fake_llm) -> AssistantService:
    return AssistantService(settings, llm=fake_llm, embedder_factory=TfidfEmbedder)


@pytest.fixture
def client(settings, service):
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_assistant_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
