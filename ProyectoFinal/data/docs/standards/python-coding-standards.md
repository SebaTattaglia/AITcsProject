---
doc_id: python-coding-standards
title: Python Coding Standards
doc_type: standard
language: python
tags: [python, style, typing, errors]
---

# Python Coding Standards

These rules apply to every Python service owned by the Application Development team. CI enforces them with `ruff`, `mypy --strict` and `pytest --cov`.

## Naming

- Modules and packages: `snake_case` (`order_service.py`).
- Classes: `PascalCase`; exceptions end in `Error` (`PaymentDeclinedError`).
- Functions, variables and parameters: `snake_case`. Booleans start with `is_`, `has_` or `should_`.
- Constants: `UPPER_SNAKE_CASE`, defined at module level.
- Avoid abbreviations except well-known ones (`id`, `url`, `db`, `http`).

## Type hints

All public functions and methods must have complete type hints, including return types. Use built-in generics (`list[str]`, `dict[str, int]`) and `X | None` instead of `Optional[X]`. `Any` requires a comment explaining why.

```python
def find_customer(customer_id: int, include_orders: bool = False) -> Customer | None:
    ...
```

## Error handling

- Never use a bare `except:` or `except Exception: pass`. Catch the narrowest exception you can handle.
- Wrap third-party exceptions in a domain exception at the boundary of the module, and chain them with `raise ... from exc` so the original traceback is preserved.
- Do not use exceptions for normal control flow.
- Log the exception once, at the layer that handles it; do not log and re-raise at every level.

```python
try:
    response = client.charge(order.total)
except StripeTimeoutError as exc:
    raise PaymentGatewayUnavailableError(order.id) from exc
```

## Functions and classes

- A function does one thing; keep it under 40 lines. More than 4 parameters means you need a dataclass or a Pydantic model.
- Prefer pure functions and dependency injection over module-level singletons; it keeps code testable.
- Never use mutable default arguments (`def f(items=[])`). Use `None` and create the list inside.

## Docstrings and comments

Public modules, classes and functions need a docstring (Google style). Comments explain *why*, not *what*. Remove commented-out code before merging.

## Testing

- Minimum line coverage per service: 80%. New code in a pull request must be covered at 90%.
- Unit tests live in `tests/unit`, integration tests in `tests/integration` and are marked `@pytest.mark.integration`.
- Use `pytest` fixtures and factories; never call real external services in unit tests — mock them at the client boundary.
