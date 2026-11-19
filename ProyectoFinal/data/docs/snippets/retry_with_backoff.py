"""Retry with exponential backoff and jitter for idempotent operations.

Approved snippet. Use it for outbound HTTP calls and deadlock retries; never retry
non-idempotent operations without an Idempotency-Key.
"""
import logging
import random
import time
from functools import wraps
from typing import Callable, TypeVar

import requests

logger = logging.getLogger(__name__)
T = TypeVar("T")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableHTTPError(Exception):
    def __init__(self, response: requests.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (requests.ConnectionError, requests.Timeout, RetryableHTTPError),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:
                    if attempt == max_attempts:
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                    delay = random.uniform(0, delay)  # full jitter avoids thundering herds
                    logger.warning("Attempt %d/%d failed (%s); retrying in %.2fs", attempt, max_attempts, exc, delay)
                    time.sleep(delay)
            raise RuntimeError("unreachable")

        return wrapper

    return decorator


session = requests.Session()  # one session per process: connection reuse


@retry_with_backoff(max_attempts=3)
def get_customer(customer_id: int) -> dict:
    response = session.get(f"https://crm.internal/api/v1/customers/{customer_id}", timeout=(3.05, 10))
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableHTTPError(response)
    response.raise_for_status()
    return response.json()
