"""Cursor-based pagination for FastAPI list endpoints.

Approved snippet that implements the REST API guidelines: limit (default 20, max 100)
and an opaque cursor, with next_cursor null on the last page.
"""
import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1")


class Page(BaseModel):
    items: list[dict]
    next_cursor: str | None


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"last_id": last_id}).encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor.encode()))["last_id"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


@router.get("/orders", response_model=Page)
def list_orders(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    repo=Depends(lambda: None),  # replace with your repository dependency
) -> Page:
    last_id = decode_cursor(cursor)
    rows = repo.fetch_orders_after(last_id, limit=limit + 1)  # one extra row tells us if there is a next page
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page(items=rows, next_cursor=encode_cursor(rows[-1]["id"]) if has_more else None)
