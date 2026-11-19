---
doc_id: logging-observability
title: Logging and Observability Guide
doc_type: guide
tags: [logging, observability, monitoring, tracing]
---

# Logging and Observability Guide

## Structured logging

All services log JSON to stdout; the platform ships it to the central log store. Free-text logs are not searchable and are rejected in code review.

Mandatory fields in every log line: `timestamp`, `level`, `service`, `environment`, `correlation_id`, `message`. Use the `structured_logging` snippet to configure it.

## Log levels

- `DEBUG`: disabled in production.
- `INFO`: business events (order created, job finished).
- `WARNING`: something unexpected that the service recovered from (retry succeeded, fallback used).
- `ERROR`: the operation failed and a human may need to act. Always include the exception.
- `CRITICAL`: the service cannot continue; pages the on-call engineer.

## Correlation ids

Read the `X-Correlation-ID` header on every inbound request, or generate a UUID4 if it is missing. Propagate it in every outbound HTTP call and message, and include it in every log line and error response.

## Metrics and alerts

Expose Prometheus metrics at `/metrics`. Every service must publish the RED metrics: request **R**ate, **E**rror rate and **D**uration (p50/p95/p99) per endpoint. Alerts fire when the 5-minute error rate is above 2% or p95 latency is above the SLO for 10 minutes.

## Tracing

Use OpenTelemetry auto-instrumentation for FastAPI, requests and SQLAlchemy. Sample 10% of traces in production and 100% of traces with errors.
