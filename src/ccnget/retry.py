"""Retry with exponential backoff for network operations.

Retries on transient errors: connection failures, timeouts, and 5xx
responses.  Used by ``lookup()`` and ``retrieve()``.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

import requests

logger: logging.Logger = logging.getLogger(__name__)

T = TypeVar("T")

# Errors that are safe to retry
_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)

# HTTP status codes that indicate a transient server problem
_RETRYABLE_STATUS: set[int] = {500, 502, 503, 504}


def retry_with_backoff(
    fn: Callable[..., T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.2,
) -> T:
    """Call *fn* with exponential backoff on transient failures.

    Retries on connection errors, timeouts, and 5xx HTTP responses.

    Parameters
    ----------
    fn : callable
        The function to call.  Must return a ``requests.Response``.
    max_retries : int
        Maximum number of retries (not counting the initial attempt).
    base_delay : float
        Initial delay in seconds between retries.
    max_delay : float
        Upper bound on the delay between retries.
    jitter : float
        Fraction of random jitter added to each delay (0-1).

    Returns
    -------
    T
        The response returned by *fn*.

    Raises
    ------
    requests.exceptions.RequestException
        The last exception after all retries are exhausted.
    requests.exceptions.HTTPError
        Raised by ``response.raise_for_status()`` for non-retryable
        HTTP errors (4xx).
    """
    last_exc: requests.exceptions.RequestException | None = None

    for attempt in range(max_retries + 1):
        try:
            response = fn()
        except _RETRYABLE as exc:
            last_exc = exc
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)
            if attempt < max_retries:
                _sleep(attempt, base_delay, max_delay, jitter)
            continue

        # Check for retryable HTTP status codes
        if isinstance(response, requests.Response) and response.status_code in _RETRYABLE_STATUS:
            last_exc = requests.exceptions.HTTPError(f"HTTP {response.status_code}", response=response)
            logger.warning("Attempt %d/%d failed: HTTP %d", attempt + 1, max_retries + 1, response.status_code)
            if attempt < max_retries:
                _sleep(attempt, base_delay, max_delay, jitter)
            continue

        if isinstance(response, requests.Response):
            response.raise_for_status()
        # Not a real Response (e.g. test mock) — return as-is
        return response  # type: ignore[return-value]

    # Exhausted retries
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_with_backoff exhausted retries without a recoverable error")


def _sleep(attempt: int, base_delay: float, max_delay: float, jitter: float) -> None:
    """Calculate and execute the backoff delay."""
    delay = min(base_delay * (2**attempt), max_delay)
    # Add random jitter to avoid thundering herd
    jitter_range = delay * jitter
    delay += random.uniform(-jitter_range, jitter_range)  # noqa: S311
    logger.debug("Waiting %.1f seconds before retry", delay)
    time.sleep(delay)
