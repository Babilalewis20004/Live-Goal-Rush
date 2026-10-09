"""Retry classification, backoff and the dead-letter record for Celery tasks (Phase 7).

A task that fails is one of:

  temporary       the provider or network hiccuped (timeout, 429, 5xx, connection reset)       -> retry
  database        Postgres was unreachable / restarting / out of connections                   -> retry
  validation      the data or arguments are malformed (it will fail identically next time)     -> do not retry
  authentication  the provider rejected our credentials (401/403)                              -> do not retry
  permanent       anything else: a bug                                                         -> do not retry

Only the first two are retried, with exponential backoff and jitter and a maximum attempt count. Everything
that finally fails -- retries exhausted or never retryable -- is written to `failed_jobs` so an administrator
can see it (`GET /api/v1/admin/failed-jobs`); nothing is silently dropped. A permanent failure is never
retried "forever", which is what turns one bad payload into a queue full of poison.
"""

from __future__ import annotations

import inspect
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.core.logging_config import request_id_var

logger = logging.getLogger(__name__)

TEMPORARY = "temporary"
DATABASE = "database"
VALIDATION = "validation"
AUTHENTICATION = "authentication"
PERMANENT = "permanent"
RETRYABLE = frozenset({TEMPORARY, DATABASE})

_BACKOFF_BASE_SECONDS = 10
_BACKOFF_CAP_SECONDS = 600
_MAX_MESSAGE = 1000
_COALESCE_WINDOW = timedelta(hours=1)


def classify(exc: BaseException) -> str:
    """Map an exception to the failure classes above. Order matters: the most specific checks come first."""
    # Imported here: pydantic and asyncpg are not needed by anything that only imports `backoff_seconds`.
    from pydantic import ValidationError

    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return AUTHENTICATION
        if code == 429 or code >= 500 or code == 408:
            return TEMPORARY
        return PERMANENT if code != 422 else VALIDATION
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, ConnectionError, TimeoutError)):
        return TEMPORARY
    # The provider layer raises these once its own in-call retries are spent; a later attempt may succeed.
    if type(exc).__name__ in {"ProviderUnavailableError"}:
        return TEMPORARY
    if isinstance(exc, (OperationalError, InterfaceError)):
        return DATABASE
    if isinstance(exc, DBAPIError):
        return DATABASE if exc.connection_invalidated else PERMANENT
    if isinstance(exc, (ValidationError, ValueError, KeyError, TypeError, LookupError)):
        return VALIDATION
    return PERMANENT


def is_retryable(exc: BaseException) -> bool:
    return classify(exc) in RETRYABLE


def backoff_seconds(retries: int) -> float:
    """10s, 20s, 40s ... capped at 10 minutes, with up to 25% jitter so retries from many tasks do not align."""
    base = min(_BACKOFF_BASE_SECONDS * (2 ** max(retries, 0)), _BACKOFF_CAP_SECONDS)
    return base * (1 + random.random() * 0.25)


def retry_or_raise(task: Any, exc: BaseException) -> None:
    """For `except Exception as exc:` blocks of bound tasks. Retries a temporary/database failure with backoff
    until `max_retries`; re-raises anything else (or the last attempt) so the failure is recorded."""
    kind = classify(exc)
    retries = task.request.retries
    if kind in RETRYABLE and retries < (task.max_retries or 0):
        delay = backoff_seconds(retries)
        logger.warning("%s failed (%s, attempt %d); retrying in %.0fs", task.name, kind, retries + 1, delay)
        raise task.retry(countdown=delay, exc=exc) from exc
    raise exc


# -- recording -------------------------------------------------------------------------------------

_SECRETISH = re.compile(r"(?i)\b(password|passwd|secret|token|api[-_]?key|apikey|authorization|bearer|signature)\b\s*[=:]\s*\S+")
_QUERY_STRING = re.compile(r"\?[^\s'\"<>]+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def scrub(text: str) -> str:
    """Error text can embed request URLs (with API keys in the query) and credentials; drop them."""
    text = _QUERY_STRING.sub("?[redacted]", text)
    text = _SECRETISH.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    text = _LONG_TOKEN.sub("[redacted]", text)
    return text[:_MAX_MESSAGE]


def describe_entity(task: Any, args: tuple, kwargs: dict) -> str | None:
    """`match:123` when the task's first `*_id` argument says what it was working on."""
    try:
        bound = inspect.signature(task.run).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        return None
    for name, value in bound.arguments.items():
        if name.endswith("_id") and isinstance(value, (int, str)):
            return f"{name[:-3]}:{value}"[:120]
    return None


async def record_failure(
    *,
    task_name: str,
    task_id: str | None,
    exc: BaseException,
    retries: int,
    entity: str | None,
    args_summary: str | None,
    request_id: str | None,
    session_factory=None,
) -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.operations import FailedJob

    kind = classify(exc)
    message = scrub(str(exc))
    now = datetime.now(timezone.utc)
    async with (session_factory or AsyncSessionLocal)() as db:
        # A task that fails on every beat tick would otherwise write a row every few seconds: fold repeats
        # of the same unresolved failure into one row and count them.
        existing = await db.scalar(
            select(FailedJob)
            .where(
                FailedJob.task_name == task_name,
                FailedJob.error_type == type(exc).__name__,
                FailedJob.entity.is_not_distinct_from(entity),
                FailedJob.resolved_at.is_(None),
                FailedJob.failed_at >= now - _COALESCE_WINDOW,
            )
            .order_by(FailedJob.failed_at.desc())
            .limit(1)
        )
        if existing is not None:
            existing.occurrences += 1
            existing.failed_at = now
            existing.error_message = message
            existing.task_id = task_id
            existing.retries = retries
        else:
            db.add(
                FailedJob(
                    task_name=task_name,
                    task_id=task_id,
                    error_type=type(exc).__name__,
                    error_message=message,
                    classification=kind,
                    retries=retries,
                    entity=entity,
                    args_summary=args_summary,
                    request_id=request_id,
                )
            )
        await db.commit()


def on_task_failure(sender: Any, task_id: str | None, exception: BaseException, args: tuple, kwargs: dict) -> None:
    """Celery `task_failure` handler body (called from `celery_app`). Must never raise: a broken database
    must not turn one failed task into a crashed worker."""
    try:
        from app.worker.async_runner import run

        retries = getattr(getattr(sender, "request", None), "retries", 0) or 0
        summary = scrub(repr((args, kwargs)))[:500] if (args or kwargs) else None
        run(
            record_failure(
                task_name=getattr(sender, "name", "unknown"),
                task_id=task_id,
                exc=exception,
                retries=retries,
                entity=describe_entity(sender, tuple(args or ()), dict(kwargs or {})),
                args_summary=summary,
                request_id=request_id_var.get(),
            )
        )
    except Exception:
        logger.warning("Could not record the failed job in the database", exc_info=True)
