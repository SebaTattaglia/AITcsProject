"""
app/core/security.py
Header-based authentication (X-API-Key) and role checks, wired as FastAPI dependencies.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class Principal:
    role: str
    key_hint: str  # never log or return the full key


def _lookup_role(api_key: str, keys: dict[str, str]) -> str | None:
    # Constant-time comparison against every configured key.
    role = None
    for candidate, candidate_role in keys.items():
        if hmac.compare_digest(candidate.encode(), api_key.encode()):
            role = candidate_role
    return role


def require_auth(
    api_key: str | None = Security(API_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    role = _lookup_role(api_key, settings.api_keys)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return Principal(role=role, key_hint=f"{api_key[:4]}…")


def require_role(*allowed_roles: str):
    """Dependency factory: require_role("admin") only lets admins through."""

    def checker(principal: Principal = Depends(require_auth)) -> Principal:
        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{principal.role}' cannot perform this action",
            )
        return principal

    return checker
