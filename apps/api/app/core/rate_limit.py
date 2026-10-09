"""Redis-backed fixed-window rate limiting (Phase 3 §21).

No rate-limit infra existed before Phase 3, so this adds one small
primitive (`RedisService.incr`, see `redis_client.py`) rather than a new
library/dependency. Fails open on Redis errors, matching `CacheAside`'s
existing "don't let infra trouble break a request" principle.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.redis_client import RedisService, get_redis_service
from app.core.redis_keys import RedisKeys
from app.services.metrics import metrics

logger = logging.getLogger(__name__)


@lru_cache
def _trusted_networks(cidrs: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks = []
    for item in cidrs.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry %r", item)
    return tuple(networks)


def client_ip(request: Request) -> str:
    """The caller's address for rate limiting and view de-duplication. The
    socket peer, unless that peer is a configured trusted proxy -- then the
    first valid `X-Forwarded-For` address it relayed."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_address in network for network in _trusted_networks(settings.trusted_proxy_cidrs)):
        return peer
    candidate = forwarded.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer


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
        identifier = client_ip(request)
        key = RedisKeys.rate_limit(bucket, identifier)
        try:
            count = await redis.incr(key, ttl_seconds=window_seconds)
        except Exception:
            logger.warning("Rate limiter failed open for bucket=%s", bucket, exc_info=True)
            return
        if count > limit:
            metrics.count("rate_limited_total")
            logger.warning("Rate limit exceeded for bucket=%s identifier=%s", bucket, identifier)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
