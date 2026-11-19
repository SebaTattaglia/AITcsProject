"""
app/core/config.py
Application settings loaded once from environment variables (.env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _path(name: str, default: str) -> Path:
    # Relative paths are resolved against the project root, not the CWD,
    # so the API, the MCP server and the scripts all see the same folders.
    path = Path(os.getenv(name, default))
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_api_keys(raw: str) -> dict[str, str]:
    """Parse "key1:role1,key2:role2" into {key: role}."""
    keys: dict[str, str] = {}
    for pair in raw.split(","):
        key, _, role = pair.strip().partition(":")
        if key and role:
            keys[key.strip()] = role.strip().lower()
    return keys


@dataclass(frozen=True)
class Settings:
    # --- LLM webhook (n8n) ---
    n8n_webhook_url: str
    n8n_webhook_timeout: int
    # --- RAG ---
    docs_dir: Path
    index_dir: Path
    chunk_tokens: int
    chunk_overlap_tokens: int
    top_k: int
    similarity_threshold: float
    min_keyword_overlap: int
    max_attempts: int
    # --- Hybrid mode + review workflow (Incident2KB style) ---
    hybrid_mode: bool
    drafts_dir: Path
    # --- Auth ---
    api_keys: dict[str, str] = field(default_factory=dict)

    @property
    def llm_configured(self) -> bool:
        return bool(self.n8n_webhook_url)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            n8n_webhook_url=os.getenv("N8N_WEBHOOK_URL", "").strip(),
            n8n_webhook_timeout=int(os.getenv("N8N_WEBHOOK_TIMEOUT", "120")),
            docs_dir=_path("DOCS_DIR", "data/docs"),
            index_dir=_path("INDEX_DIR", "data/index"),
            chunk_tokens=int(os.getenv("CHUNK_TOKENS", "350")),
            chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "60")),
            top_k=int(os.getenv("TOP_K", "4")),
            similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.25")),
            min_keyword_overlap=int(os.getenv("MIN_KEYWORD_OVERLAP", "1")),
            max_attempts=int(os.getenv("MAX_ATTEMPTS", "2")),
            hybrid_mode=os.getenv("HYBRID_MODE", "true").strip().lower() in {"1", "true", "yes", "on"},
            drafts_dir=_path("DRAFTS_DIR", "data/drafts"),
            api_keys=_parse_api_keys(os.getenv("API_KEYS", "")),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
