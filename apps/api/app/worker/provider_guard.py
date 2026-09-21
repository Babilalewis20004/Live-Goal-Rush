"""Provider rate-limit protection (Phase 2 §10).

Every provider call the worker makes goes through `call_with_backoff`,
which tracks request/error/429 counts (spec §27's
`provider_requests_total`/`provider_errors_total`) and retries with
exponential backoff -- explicitly not retrying immediately on a 429 --
up to `SYNC_MAX_RETRIES` before giving up on that sync cycle.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.core.config import settings
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderUnavailableError(Exception):
    """Raised when a provider call exhausts its retries. Sync tasks catch
    this, log it, and skip that cycle rather than crash the worker process
    or propagate a 500 to any client (spec §22)."""


async def call_with_backoff(operation: str, fn: Callable[[], Awaitable[T]]) -> T:
    attempt = 0
    while True:
        attempt += 1
        metrics.provider_request()
        try:
            return await fn()
        except httpx.HTTPStatusError as exc:
            metrics.provider_error()
            if exc.response.status_code == 429:
                metrics.provider_rate_limited()
                logger.warning("Provider rate-limited on %s (attempt %d)", operation, attempt)
            else:
                logger.warning("Provider error on %s: %s (attempt %d)", operation, exc, attempt)
        except Exception:
            metrics.provider_error()
            logger.warning("Provider call failed on %s (attempt %d)", operation, attempt, exc_info=True)

        if attempt >= settings.sync_max_retries:
            raise ProviderUnavailableError(f"{operation} failed after {attempt} attempt(s)")

        backoff_seconds = settings.sync_backoff_seconds * (2 ** (attempt - 1))
        logger.info("Backing off %.1fs before retrying %s (attempt %d)", backoff_seconds, operation, attempt)
        await asyncio.sleep(backoff_seconds)
