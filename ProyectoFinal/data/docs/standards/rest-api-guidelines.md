---
doc_id: rest-api-guidelines
title: REST API Design Guidelines
doc_type: standard
tags: [api, rest, http, fastapi]
---

# REST API Design Guidelines

## URLs and versioning

- Resources are plural nouns: `/api/v1/orders`, `/api/v1/orders/{order_id}/items`.
- The major version goes in the path (`/api/v1`). Breaking changes require a new major version; the previous one is supported for 6 months after deprecation is announced.
- Use `kebab-case` for multi-word path segments and `snake_case` for JSON fields.

## HTTP methods and status codes

| Operation | Method | Success code |
|---|---|---|
| List / read | GET | 200 |
| Create | POST | 201 + `Location` header |
| Partial update | PATCH | 200 |
| Delete | DELETE | 204 |

- 400 malformed request, 401 missing or invalid credentials, 403 authenticated but not allowed, 404 resource not found, 409 conflict (e.g. duplicate), 422 validation error, 429 rate limited, 503 dependency unavailable.
- Never return 200 with an error body.

## Error format

Every error uses the same JSON body so clients can handle it generically:

```json
{
  "error": {
    "code": "ORDER_NOT_FOUND",
    "message": "Order 4821 does not exist",
    "correlation_id": "7f3c2a90-1b7e-4d1c-9a55-0c2f6e8d1f42"
  }
}
```

## Pagination

Collections are paginated with `limit` (default 20, max 100) and an opaque `cursor`. Responses include `next_cursor` (null on the last page). Offset pagination is not allowed on tables above 100k rows because of its cost.

## Authentication

Service-to-service calls use OAuth2 client credentials. Internal tools may use an `X-API-Key` header injected from the secrets vault. Keys are never accepted as query parameters because URLs end up in logs.

## Idempotency

`POST` endpoints that create payments or orders must accept an `Idempotency-Key` header and return the original response when the same key is replayed within 24 hours.
