"""Redis service abstraction (Phase 2 §3).

Two clients are exposed rather than one, because FastAPI's request handlers
are async (`redis.asyncio`) while Celery's task execution model is
synchronous (`redis`, sync). Both wrap the same responsibilities
(get/set/delete/expire/publish/subscribe/health_check) with JSON
serialization for structured football data, so nothing outside this module
touches `redis-py` directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache
from typing import Any, TypeVar

import redis as redis_sync
import redis.asyncio as redis_async
from redis import exceptions as redis_exceptions

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Without timeouts redis-py waits for the operating system to give up on an unreachable host -- minutes. A stopped Redis
# container therefore froze every request that touched it (found by stopping Redis under load in Phase 7). Commands now
# fail in about two seconds, and after one failure the breaker below fails the rest instantly.
CONNECT_TIMEOUT_SECONDS = 1.0
COMMAND_TIMEOUT_SECONDS = 2.0
_UNAVAILABLE = (redis_exceptions.ConnectionError, redis_exceptions.TimeoutError, OSError, asyncio.TimeoutError)


class CircuitBreaker:
    """After a connection failure, refuse further attempts for `open_seconds` (raising immediately) instead of making
    every request wait out its own timeout; the first attempt after that window is the probe that closes it again."""

    def __init__(self, open_seconds: float = 5.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.open_seconds = open_seconds
        self._clock = clock
        self._open_until = 0.0

    @property
    def is_open(self) -> bool:
        return self._clock() < self._open_until

    def before_call(self) -> None:
        if self.is_open:
            raise redis_exceptions.ConnectionError("Redis is unavailable (circuit open after a recent failure)")

    def record_failure(self) -> None:
        self._open_until = self._clock() + self.open_seconds

    def record_success(self) -> None:
        self._open_until = 0.0


class RedisService:
    """Async Redis wrapper used by FastAPI request handlers and the
    WebSocket pub/sub bridge."""

    def __init__(self, url: str, *, client: redis_async.Redis | None = None) -> None:
        # `client` is accepted directly (rather than only ever built from a
        # URL) so tests can inject a fakeredis client without monkeypatching
        # `redis.asyncio.from_url`.
        self._url = url
        self._injected = client is not None
        self._client: redis_async.Redis = client or redis_async.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            socket_timeout=COMMAND_TIMEOUT_SECONDS,
            health_check_interval=30,
        )
        self._subscriber_client: redis_async.Redis | None = None
        self.breaker = CircuitBreaker()

    async def _guard(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run one Redis call under the breaker: fail instantly while it is open, open it on a connection failure."""
        self.breaker.before_call()
        try:
            result = await operation()
        except _UNAVAILABLE:
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return result

    async def get(self, key: str) -> Any | None:
        raw = await self._guard(lambda: self._client.get(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        await self._guard(lambda: self._client.set(key, json.dumps(value), ex=ttl_seconds))

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._guard(lambda: self._client.delete(*keys))

    async def expire(self, key: str, ttl_seconds: int) -> None:
        await self._guard(lambda: self._client.expire(key, ttl_seconds))

    async def incr(self, key: str, *, ttl_seconds: int) -> int:
        """Fixed-window rate-limit counter (Phase 3 §21): increments `key`
        and sets its TTL only on the window's first increment, so the
        window doesn't keep sliding forward on every subsequent request."""
        # INCR and EXPIRE NX in one MULTI/EXEC: a crash between two separate commands used to leave a counter
        # with no TTL, which for a rate limit means a client blocked forever.
        async def _go() -> int:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, ttl_seconds, nx=True)
                count, _ = await pipe.execute()
            return count

        return await self._guard(_go)

    async def publish(self, channel: str, message: dict) -> None:
        await self._guard(lambda: self._client.publish(channel, json.dumps(message)))

    def _subscriber(self) -> redis_async.Redis:
        """Pub/sub waits for messages for as long as it takes, so it must not share the command timeout: it gets its own
        connection with only a connect timeout and periodic health-check pings (which also detect a dead connection)."""
        if self._injected:
            return self._client
        if self._subscriber_client is None:
            self._subscriber_client = redis_async.from_url(
                self._url, decode_responses=True, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS, health_check_interval=15
            )
        return self._subscriber_client

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        """Yields decoded JSON messages published to `channel` until the
        caller stops iterating (e.g. on task cancellation)."""
        pubsub = self._subscriber().pubsub()
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

    @property
    def raw(self) -> redis_async.Redis:
        """The underlying async client (see `SyncRedisService.raw`)."""
        return self._client

    async def aclose(self) -> None:
        await self._client.aclose()
        if self._subscriber_client is not None:
            await self._subscriber_client.aclose()


class SyncRedisService:
    """Sync Redis wrapper used by Celery worker/beat tasks."""

    def __init__(self, url: str, *, client: redis_sync.Redis | None = None) -> None:
        self._client: redis_sync.Redis = client or redis_sync.from_url(
            url, decode_responses=True, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS, socket_timeout=5.0, health_check_interval=30
        )

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

    def incr(self, key: str, *, ttl_seconds: int) -> int:
        pipe = self._client.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, ttl_seconds, nx=True)
        count, _ = pipe.execute()
        return count

    def publish(self, channel: str, message: dict) -> None:
        self._client.publish(channel, json.dumps(message))

    def health_check(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            logger.warning("Redis health check failed", exc_info=True)
            return False

    @property
    def raw(self) -> redis_sync.Redis:
        """The underlying client, for the metrics sink's hash/pipeline
        operations (which don't fit this wrapper's JSON get/set API)."""
        return self._client


@lru_cache
def get_redis_service() -> RedisService:
    return RedisService(settings.redis_url)


@lru_cache
def get_sync_redis_service() -> SyncRedisService:
    return SyncRedisService(settings.redis_url)
