"""On-demand background sync requests from read endpoints (Phase 4).

Reads never call the provider (Phase 2 §5). When a read finds data the
provider could supply but we haven't stored yet -- an empty squad, a player
who only exists because a match event mentioned them -- it asks the worker
to fetch it, at most once per window per entity, and returns what it has.
The client shows an honest "still loading" state and picks the data up on
its next refresh.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.config import settings
from app.core.redis_keys import RedisKeys
from app.services.cache import CacheAside

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SECONDS = 3600


async def request_sync_once(
    cache: CacheAside | None,
    kind: str,
    identifier: int | str,
    enqueue: Callable[[], object],
    *,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> bool:
    """Runs `enqueue` unless a request for (kind, identifier) was already
    made within the window. Returns whether it was enqueued. No cache (no
    Redis) means no debounce state, so nothing is enqueued -- safer than
    enqueuing on every request."""
    if cache is None:
        return False
    key = RedisKeys.sync_requested(kind, identifier)
    try:
        if await cache.redis.get(key) is not None:
            return False
        # Global budget: a burst of *different* ids (scraping player ids) must
        # not become a burst of provider calls.
        used = await cache.redis.incr(RedisKeys.sync_requested("budget", kind), ttl_seconds=60)
        if used > settings.sync_request_budget_per_minute:
            logger.warning("Sync-request budget exhausted for %s; not enqueueing %s", kind, identifier)
            return False
        await cache.redis.set(key, 1, ttl_seconds=window_seconds)
    except Exception:
        logger.warning("Sync-request debounce unavailable for %s:%s", kind, identifier, exc_info=True)
        return False
    try:
        enqueue()
    except Exception:
        logger.warning("Failed to enqueue %s sync for %s", kind, identifier, exc_info=True)
        return False
    return True
