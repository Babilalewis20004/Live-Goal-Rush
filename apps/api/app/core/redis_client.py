"""Redis service abstraction (Phase 2 §3).

Two clients are exposed rather than one, because FastAPI's request handlers
are async (`redis.asyncio`) while Celery's task execution model is
synchronous (`redis`, sync). Both wrap the same responsibilities
(get/set/delete/expire/publish/subscribe/health_check) with JSON
serialization for structured football data, so nothing outside this module
touches `redis-py` directly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import redis as redis_sync
import redis.asyncio as redis_async

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisService:
    """Async Redis wrapper used by FastAPI request handlers and the
    WebSocket pub/sub bridge."""

    def __init__(self, url: str, *, client: redis_async.Redis | None = None) -> None:
        # `client` is accepted directly (rather than only ever built from a
        # URL) so tests can inject a fakeredis client without monkeypatching
        # `redis.asyncio.from_url`.
        self._client: redis_async.Redis = client or redis_async.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        await self._client.set(key, json.dumps(value), ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def expire(self, key: str, ttl_seconds: int) -> None:
        await self._client.expire(key, ttl_seconds)

    async def publish(self, channel: str, message: dict) -> None:
        await self._client.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        """Yields decoded JSON messages published to `channel` until the
        caller stops iterating (e.g. on task cancellation)."""
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    yield json.loads(message["data"])
                except (TypeError, ValueError):
                    logger.warning("Discarding malformed pub/sub message on %s", channel)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def health_check(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:
            logger.warning("Redis health check failed", exc_info=True)
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class SyncRedisService:
    """Sync Redis wrapper used by Celery worker/beat tasks."""

    def __init__(self, url: str, *, client: redis_sync.Redis | None = None) -> None:
        self._client: redis_sync.Redis = client or redis_sync.from_url(url, decode_responses=True)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._client.set(key, json.dumps(value), ex=ttl_seconds)

    def delete(self, *keys: str) -> None:
        if keys:
            self._client.delete(*keys)

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._client.expire(key, ttl_seconds)

    def publish(self, channel: str, message: dict) -> None:
        self._client.publish(channel, json.dumps(message))

    def health_check(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            logger.warning("Redis health check failed", exc_info=True)
            return False


@lru_cache
def get_redis_service() -> RedisService:
    return RedisService(settings.redis_url)


@lru_cache
def get_sync_redis_service() -> SyncRedisService:
    return SyncRedisService(settings.redis_url)
