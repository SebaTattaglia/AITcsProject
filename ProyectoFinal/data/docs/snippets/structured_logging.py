"""Structured JSON logging with correlation ids for FastAPI services.

Approved snippet that implements the logging guide: JSON to stdout, mandatory fields,
X-Correlation-ID propagation and masking of secrets.
"""
import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "authorization"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": os.getenv("SERVICE_NAME", "unknown"),
            "environment": os.getenv("ENVIRONMENT", "local"),
            "correlation_id": correlation_id.get(),
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = f"{str(value)[:4]}…" if key.lower() in SENSITIVE_KEYS else value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def add_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id.set(cid)
        try:
            response = await call_next(request)
        finally:
            correlation_id.reset(token)
        response.headers["X-Correlation-ID"] = cid
        return response
