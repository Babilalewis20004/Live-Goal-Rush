"""WebSocket connection manager (Phase 2 §15).

Owns all connection bookkeeping -- connect/disconnect/broadcast/match
subscriptions/dead-connection cleanup -- so this logic doesn't leak into
`FootballService` or the route handlers (spec: "Do not put WebSocket
connection logic directly inside business services"). One instance per API
process (`manager` below); it has no knowledge of Redis or the worker --
`app/websocket/pubsub_bridge.py` is the only thing that calls into it from
outside `app/api/v1/websocket.py`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict

from fastapi import WebSocket

from app.core.config import settings
from app.services.metrics import metrics

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.general_connections: set[WebSocket] = set()
        self.match_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._ip_of: dict[WebSocket, str] = {}
        self._per_ip: Counter[str] = Counter()

    def connection_count(self) -> int:
        return len(self.general_connections) + sum(len(s) for s in self.match_connections.values())

    def at_capacity(self, max_connections: int) -> bool:
        return self.connection_count() >= max_connections

    def ip_at_capacity(self, ip: str, max_per_ip: int) -> bool:
        """One address may not hold the whole connection budget (0 disables the per-address cap)."""
        return max_per_ip > 0 and self._per_ip[ip] >= max_per_ip

    def _track(self, websocket: WebSocket, ip: str | None) -> None:
        if ip is not None:
            self._ip_of[websocket] = ip
            self._per_ip[ip] += 1

    def _untrack(self, websocket: WebSocket) -> None:
        ip = self._ip_of.pop(websocket, None)
        if ip is not None:
            self._per_ip[ip] -= 1
            if self._per_ip[ip] <= 0:
                del self._per_ip[ip]

    async def connect_general(self, websocket: WebSocket, ip: str | None = None) -> None:
        await websocket.accept()
        self.general_connections.add(websocket)
        self._track(websocket, ip)
        metrics.websocket_connected()
        logger.info("WebSocket connected (general); %d total", self.connection_count())

    async def connect_match(self, websocket: WebSocket, match_id: str, ip: str | None = None) -> None:
        await websocket.accept()
        self.match_connections[match_id].add(websocket)
        self._track(websocket, ip)
        metrics.websocket_connected()
        logger.info("WebSocket connected (match %s); %d total", match_id, self.connection_count())

    def disconnect_general(self, websocket: WebSocket) -> None:
        if websocket in self.general_connections:
            self.general_connections.discard(websocket)
            self._untrack(websocket)
            metrics.websocket_disconnected()
            logger.info("WebSocket disconnected (general); %d total", self.connection_count())

    def disconnect_match(self, websocket: WebSocket, match_id: str) -> None:
        connections = self.match_connections.get(match_id)
        if connections and websocket in connections:
            connections.discard(websocket)
            self._untrack(websocket)
            if not connections:
                self.match_connections.pop(match_id, None)
            metrics.websocket_disconnected()
            logger.info("WebSocket disconnected (match %s); %d total", match_id, self.connection_count())

    async def broadcast_general(self, message: dict) -> None:
        await self._send_to_many(self.general_connections, message)

    async def broadcast_to_match(self, match_id: str, message: dict) -> None:
        connections = self.match_connections.get(match_id)
        if connections:
            await self._send_to_many(connections, message)

    async def _send_to_many(self, connections: set[WebSocket], message: dict) -> None:
        """Deliver to every socket concurrently, each under a deadline. Sequential, unbounded sends meant one
        client with a stalled TCP window (a phone that lost signal without closing) blocked every other
        client's update; now it is cut off after `websocket_send_timeout_seconds` and everyone else is unaffected."""
        targets = list(connections)
        if not targets:
            return
        outcomes = await asyncio.gather(*(self._send_one(websocket, message) for websocket in targets))
        for websocket, delivered in zip(targets, outcomes):
            if delivered:
                metrics.websocket_message_sent()
            else:
                connections.discard(websocket)
                self._untrack(websocket)
                metrics.websocket_disconnected()
                metrics.count("websocket_clients_evicted_total")
                asyncio.ensure_future(self._drop(websocket))

    @staticmethod
    async def _send_one(websocket: WebSocket, message: dict) -> bool:
        try:
            await asyncio.wait_for(websocket.send_json(message), timeout=settings.websocket_send_timeout_seconds)
            return True
        except Exception:
            return False

    @staticmethod
    async def _drop(websocket: WebSocket) -> None:
        """Release the transport of a client that stopped reading; never raises."""
        try:
            await asyncio.wait_for(websocket.close(code=1013), timeout=1)  # 1013: try again later
        except Exception:
            pass


manager = ConnectionManager()
