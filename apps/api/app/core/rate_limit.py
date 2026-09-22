"""Redis-backed fixed-window rate limiting (Phase 3 §21).

No rate-limit infra existed before Phase 3, so this adds one small
primitive (`RedisService.incr`, see `redis_client.py`) rather than a new
library/dependency. Fails open on Redis errors, matching `CacheAside`'s
existing "don't let infra trouble break a request" principle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from app.core.redis_client import RedisService, get_redis_service
from app.core.redis_keys import RedisKeys

logger = logging.getLogger(__name__)


def rate_limiter(
    bucket: str, limit: int, window_seconds: int
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Returns a FastAPI dependency limiting requests to `limit` per
    `window_seconds`, keyed by the caller's IP within `bucket`. Used as
    `Depends(rate_limiter("register", 5, 3600))` on a route. `redis` is
    taken as a real sub-dependency (not called directly) so tests can
    override `get_redis_service` with fakeredis, same as every other
    Redis-touching endpoint."""

    async def _dependency(
        request: Request,
        redis: Annotated[RedisService, Depends(get_redis_service)],
    ) -> None:
        identifier = request.client.host if request.client else "unknown"
        key = RedisKeys.rate_limit(bucket, identifier)
        try:
            count = await redis.incr(key, ttl_seconds=window_seconds)
        except Exception:
            logger.warning("Rate limiter failed open for bucket=%s", bucket, exc_info=True)
            return
        if count > limit:
            logger.warning("Rate limit exceeded for bucket=%s identifier=%s", bucket, identifier)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
