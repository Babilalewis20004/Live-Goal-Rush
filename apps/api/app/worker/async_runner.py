"""Shared persistent-event-loop helper for Celery tasks (Phase 2 §6,
extracted in Phase 3 so `worker/notification_tasks.py` can reuse it
without importing `worker/tasks.py`, which would be a circular-ish,
unrelated-concern import between the sync pipeline and notification
dispatch).
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_worker_loop: asyncio.AbstractEventLoop | None = None


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Runs `coro` to completion on one event loop that lives for this
    worker process's whole lifetime, not a fresh one per task.

    `asyncio.run()` per task looks correct but isn't: `app.db.session`'s
    async SQLAlchemy engine (and its pooled asyncpg connections) is a
    process-wide singleton created on first use, and asyncpg connections
    are bound to the event loop they were opened on. A prefork Celery
    worker executes many tasks over its process lifetime; tearing down and
    recreating the loop on every single one (what `asyncio.run` does)
    leaves the *next* task's pooled connections attached to a now-dead
    loop, which surfaces as an intermittent
    `RuntimeError: ... got Future ... attached to a different loop`.
    """
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop.run_until_complete(coro)
