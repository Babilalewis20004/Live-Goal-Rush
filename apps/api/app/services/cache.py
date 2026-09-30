"""Cache-aside helpers (Phase 2 §5).

`FootballService` uses these instead of touching `RedisService` directly:
check Redis, and on a miss call the provided loader (which reads from
Postgres) and populate the cache. Structured football data is stored as
the Pydantic response model's JSON-mode dump, so a cache hit reconstructs
into the exact schema the router returns -- callers never see a raw dict.

If Redis itself is unreachable, every operation here falls back to calling
the loader directly rather than raising -- a cache outage degrades response
times, not availability (Phase 2 §22's "don't crash on infra failure"
principle applied to the cache layer, not just the provider).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from app.core.redis_client import RedisService
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class CacheAside:
    def __init__(self, redis: RedisService) -> None:
        self.redis = redis

    async def _safe_get(self, key: str):
        try:
            return await self.redis.get(key)
        except Exception:
            logger.warning("Redis GET failed for %s; falling back to the database", key, exc_info=True)
            return None

    async def _safe_set(self, key: str, value, *, ttl_seconds: int) -> None:
        try:
            await self.redis.set(key, value, ttl_seconds=ttl_seconds)
        except Exception:
            logger.warning("Redis SET failed for %s; continuing without caching it", key, exc_info=True)

    async def get_or_set_model(
        self,
        key: str,
        model: type[T],
        loader: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: int | Callable[[], int],
    ) -> T:
        """`ttl_seconds` may be a callable, evaluated *after* the loader ran:
        for data whose freshness depends on something the loader looked up
        (e.g. a match's status), so a cache hit never needs that lookup."""
        cached = await self._safe_get(key)
        if cached is not None:
            metrics.cache_hit()
            return model.model_validate(cached)

        metrics.cache_miss()
        value = await loader()
        ttl = ttl_seconds() if callable(ttl_seconds) else ttl_seconds
        await self._safe_set(key, value.model_dump(mode="json"), ttl_seconds=ttl)
        return value

    async def get_or_set_list(
        self,
        key: str,
        model: type[T],
        loader: Callable[[], Awaitable[list[T]]],
        *,
        ttl_seconds: int,
    ) -> list[T]:
        cached = await self._safe_get(key)
        if cached is not None:
            metrics.cache_hit()
            adapter: TypeAdapter[list[T]] = TypeAdapter(list[model])
            return adapter.validate_python(cached)

        metrics.cache_miss()
        values = await loader()
        await self._safe_set(key, [v.model_dump(mode="json") for v in values], ttl_seconds=ttl_seconds)
        return values

    async def invalidate(self, *keys: str) -> None:
        try:
            await self.redis.delete(*keys)
        except Exception:
            logger.warning("Redis DELETE failed for %s", keys, exc_info=True)
