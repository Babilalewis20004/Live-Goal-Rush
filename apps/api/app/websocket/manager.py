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

import logging
from collections import defaultdict

from fastapi import WebSocket

from app.services.metrics import metrics

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.general_connections: set[WebSocket] = set()
        self.match_connections: dict[str, set[WebSocket]] = defaultdict(set)

    def connection_count(self) -> int:
        return len(self.general_connections) + sum(len(s) for s in self.match_connections.values())

    def at_capacity(self, max_connections: int) -> bool:
        return self.connection_count() >= max_connections

    async def connect_general(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.general_connections.add(websocket)
        metrics.websocket_connected()
        logger.info("WebSocket connected (general); %d total", self.connection_count())

    async def connect_match(self, websocket: WebSocket, match_id: str) -> None:
        await websocket.accept()
        self.match_connections[match_id].add(websocket)
        metrics.websocket_connected()
        logger.info("WebSocket connected (match %s); %d total", match_id, self.connection_count())

    def disconnect_general(self, websocket: WebSocket) -> None:
        if websocket in self.general_connections:
            self.general_connections.discard(websocket)
            metrics.websocket_disconnected()
            logger.info("WebSocket disconnected (general); %d total", self.connection_count())

    def disconnect_match(self, websocket: WebSocket, match_id: str) -> None:
        connections = self.match_connections.get(match_id)
        if connections and websocket in connections:
            connections.discard(websocket)
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
        dead: list[WebSocket] = []
        for websocket in list(connections):
            try:
                await websocket.send_json(message)
                metrics.websocket_message_sent()
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            connections.discard(websocket)
            metrics.websocket_disconnected()


manager = ConnectionManager()
