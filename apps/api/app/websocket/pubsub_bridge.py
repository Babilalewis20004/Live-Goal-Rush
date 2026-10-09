"""Bridges Redis Pub/Sub (published by the worker's change-detection step)
to the in-process `ConnectionManager` (Phase 2 §13). One instance runs as a
background task per API process, started from `app/main.py`'s lifespan.
The worker never imports this module and never knows a WebSocket exists --
it only publishes to `RedisKeys.MATCH_EVENTS_CHANNEL`.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.redis_client import RedisService
from app.core.redis_keys import RedisKeys
from app.events.community import COMMUNITY_EVENT_TYPES
from app.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 2


_MATCH_ONLY_TYPES = frozenset(t.value for t in COMMUNITY_EVENT_TYPES)

class PubSubBridge:
    def __init__(self, redis: RedisService, manager: ConnectionManager) -> None:
        self.redis = redis
        self.manager = manager
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            try:
                async for message in self.redis.subscribe(RedisKeys.MATCH_EVENTS_CHANNEL):
                    await self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Pub/sub bridge lost its Redis subscription; retrying in %ds",
                    _RECONNECT_DELAY_SECONDS,
                )
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    async def _dispatch(self, message: dict) -> None:
        match_id = str(message.get("match_id", ""))
        payload = {"type": message.get("type"), "match": {"id": match_id, **message.get("data", {})}}
        logger.info("WebSocket broadcast: %s for match %s", payload["type"], match_id)
        # Community/analytics nudges are for people on that match's page, not the livescore board.
        if payload["type"] not in _MATCH_ONLY_TYPES:
            await self.manager.broadcast_general(payload)
        if match_id:
            await self.manager.broadcast_to_match(match_id, payload)
