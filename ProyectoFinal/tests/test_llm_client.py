import dataclasses

import pytest
import requests

from app.core.config import Settings
from app.services import llm_client
from app.services.llm_client import LLMWebhookError, _parse_response, call_llm


class FakeResponse:
    def __init__(self, status_code=200, body=None, text="", content_type="application/json"):
        self.status_code = status_code
        self.ok = status_code < 400
        self._body = body
        self.text = text
        self.headers = {"Content-Type": content_type}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture
def webhook_settings() -> Settings:
    return dataclasses.replace(
        Settings.from_env(), n8n_webhook_url="https://example.ngrok-free.dev/webhook/test"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"output": " hi "},                         # n8n AI Agent node
        {"article": "hi"},                          # Incident2KB-style workflow
        {"text": "hi"},
        [{"output": "hi"}],                         # "Respond with all incoming items"
        {"choices": [{"message": {"content": "hi"}}]},  # OpenAI body passed through
        "hi",
    ],
)
def test_parse_response_shapes(body):
    assert _parse_response(body) == "hi"


def test_call_llm_posts_system_and_prompt_without_auth(monkeypatch, webhook_settings):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers)
        return FakeResponse(body={"output": "ok"})

    monkeypatch.setattr(llm_client.requests, "post", fake_post)

    assert call_llm("question", "system", settings=webhook_settings) == "ok"
    assert captured["url"] == webhook_settings.n8n_webhook_url
    assert captured["json"] == {"system": "system", "prompt": "question"}
    assert "Authorization" not in captured["headers"]


def test_call_llm_accepts_plain_text(monkeypatch, webhook_settings):
    monkeypatch.setattr(
        llm_client.requests, "post",
        lambda *a, **k: FakeResponse(text="plain answer", content_type="text/plain"),
    )

    assert call_llm("q", "s", settings=webhook_settings) == "plain answer"


def test_call_llm_raises_on_http_error(monkeypatch, webhook_settings):
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: FakeResponse(404, text="webhook not registered"))

    with pytest.raises(LLMWebhookError, match="HTTP 404"):
        call_llm("q", "s", settings=webhook_settings)


def test_call_llm_raises_on_unknown_json(monkeypatch, webhook_settings):
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: FakeResponse(body={"foo": "bar"}, text='{"foo":"bar"}'))

    with pytest.raises(LLMWebhookError, match="none of the keys"):
        call_llm("q", "s", settings=webhook_settings)


def test_call_llm_raises_on_timeout(monkeypatch, webhook_settings):
    def boom(*args, **kwargs):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(llm_client.requests, "post", boom)

    with pytest.raises(LLMWebhookError, match="timed out"):
        call_llm("q", "s", settings=webhook_settings)


def test_call_llm_requires_url(webhook_settings):
    with pytest.raises(LLMWebhookError, match="N8N_WEBHOOK_URL"):
        call_llm("q", "s", settings=dataclasses.replace(webhook_settings, n8n_webhook_url=""))
