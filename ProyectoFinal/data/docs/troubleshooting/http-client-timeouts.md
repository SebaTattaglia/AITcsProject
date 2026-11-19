---
doc_id: troubleshooting-http-timeouts
title: Troubleshooting Timeouts with Downstream APIs
doc_type: troubleshooting
tags: [http, timeout, retry, circuit-breaker, requests]
---

# Troubleshooting Timeouts with Downstream APIs

## Symptoms

Requests to a downstream service fail intermittently with `ReadTimeout` or `ConnectTimeout`, or our own endpoint latency grows until the load balancer returns 504.

## Rules for every outbound HTTP call

- Always set explicit timeouts. `requests` has **no default timeout** and can hang forever. Use `timeout=(3.05, 10)` (connect, read) unless the downstream SLA says otherwise.
- Retry only idempotent operations (GET, PUT, DELETE, or POST with an `Idempotency-Key`).
- Retry on connection errors, timeouts, 429 and 5xx; never on other 4xx.
- Use exponential backoff with jitter, max 3 attempts (see the `retry_with_backoff` snippet). Respect the `Retry-After` header on 429.
- Wrap critical dependencies with a circuit breaker: open after 5 consecutive failures, half-open after 30 seconds.

## Diagnosis steps

1. Check the downstream service dashboard for its own latency and error rate.
2. Look for the `correlation_id` in both services' logs to see where the time is spent.
3. Verify DNS and connection reuse: create one `requests.Session` per process instead of one per call.
4. If only some pods fail, check node-level network issues and egress proxy limits.
