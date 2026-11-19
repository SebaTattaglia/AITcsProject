#!/usr/bin/env python
"""
scripts/check_webhook.py
Quick test to verify the n8n LLM webhook responds with text the assistant can use.

Run: python scripts/check_webhook.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.llm_client import LLMWebhookError, call_llm  # noqa: E402

settings = get_settings()

print("=" * 60)
print("Dev Knowledge Assistant - n8n webhook connection test")
print("=" * 60)
print(f"Webhook URL : {settings.n8n_webhook_url or 'NOT SET'}")
print(f"Timeout     : {settings.n8n_webhook_timeout}s")
print()

print("Sending test request...")
try:
    reply = call_llm("Reply with exactly: CONNECTION_OK", "You are a connectivity probe.")
except LLMWebhookError as exc:
    print(f"[FAIL] {exc}")
    sys.exit(1)

print(f"Response: {reply[:500]}")
print("[OK] Webhook reachable")
if "CONNECTION_OK" not in reply:
    print(
        "[WARN] The reply does not follow the instruction. Check that the n8n workflow\n"
        "       uses {{ $json.body.system }} and {{ $json.body.prompt }} in its AI node."
    )
