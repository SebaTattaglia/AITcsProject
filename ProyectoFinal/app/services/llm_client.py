"""
app/services/llm_client.py
LLM access through an n8n webhook, POST JSON to the webhook URL (exposed via ngrok),
no API key, and accept either plain text or JSON {"output" | "article" | "text" | "result"}.

The n8n workflow owns the model (gpt-4.1-mini); this client only sends:
    {"system": "<instructions>", "prompt": "<question + context>"}

Unlike the reference (which returns "[ERROR] ..." strings), failures raise
LLMWebhookError so the LangGraph nodes can decide how to degrade.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import requests

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# (prompt, system) -> text. Every node depends on this signature, so tests can inject a fake.
LLMFn = Callable[[str, str], str]

RESPONSE_KEYS = ("output", "article", "text", "result", "response", "answer")


class LLMWebhookError(RuntimeError):
    """The LLM webhook could not produce a usable answer."""


def _parse_response(data: Any) -> str | None:
    """Extract the generated text from the shapes n8n can return."""
    if isinstance(data, str):
        return data.strip() or None
    if isinstance(data, list) and data:
        # "Respond to Webhook" with "All Incoming Items" returns a list.
        return _parse_response(data[0])
    if isinstance(data, dict):
        for key in RESPONSE_KEYS:
            if data.get(key):
                return str(data[key]).strip()
        if data.get("choices"):  # an OpenAI-shaped body passed straight through
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content") or choice.get("text")
            return content.strip() if content else None
        if isinstance(data.get("json"), dict):  # raw n8n item
            return _parse_response(data["json"])
    return None


def call_llm(prompt: str, system: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not settings.n8n_webhook_url:
        raise LLMWebhookError("N8N_WEBHOOK_URL is not set in your .env file.")

    try:
        response = requests.post(
            settings.n8n_webhook_url,
            json={"system": system, "prompt": prompt},
            # ngrok-free serves an HTML warning page unless this header is present
            headers={"ngrok-skip-browser-warning": "true"},
            timeout=(10, settings.n8n_webhook_timeout),
        )
    except requests.exceptions.Timeout as exc:
        raise LLMWebhookError(f"Webhook request timed out after {settings.n8n_webhook_timeout}s.") from exc
    except requests.exceptions.RequestException as exc:
        raise LLMWebhookError(f"Webhook request failed: {str(exc)[:300]}") from exc

    if not response.ok:
        raise LLMWebhookError(f"Webhook returned HTTP {response.status_code}: {response.text[:300]}")

    # n8n can respond with plain text or JSON
    if "application/json" in response.headers.get("Content-Type", ""):
        try:
            parsed = _parse_response(response.json())
        except ValueError:
            parsed = _parse_response(response.text)
        if not parsed:
            raise LLMWebhookError(
                f"Webhook JSON has none of the keys {RESPONSE_KEYS}: {response.text[:200]}"
            )
        return parsed

    parsed = _parse_response(response.text)
    if not parsed:
        raise LLMWebhookError("Webhook returned an empty response.")
    return parsed
