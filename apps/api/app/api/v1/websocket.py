"""WebSocket endpoints (Phase 2 §14).

`/ws/matches` -- general live-match updates, for the home/livescore board.
`/ws/matches/{match_id}` -- updates scoped to one match, for the match
detail page; only clients subscribed to that match's connection set
receive its updates (spec §16), so a busy general feed doesn't also get
pushed to every match-detail viewer.

Security (spec §29): origin is checked against the same allow-list CORS
uses, connections are capped per process, and inbound messages are
size/JSON validated. There's no user auth in this app (Phase 1 never added
any), so this is "authentication-ready" -- `_origin_allowed`/the connect
path is exactly where a token check would go -- rather than actually
authenticated.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import settings
from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_MESSAGE_BYTES = 2048


def _origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        # Non-browser clients (native mobile apps, curl, server-to-server
        # health checks) don't send an Origin header at all -- only reject
        # requests that *do* send one we don't recognize.
        return True
    return origin in settings.cors_origin_list


async def _receive_loop(websocket: WebSocket) -> None:
    """Keeps the connection open, validating/discarding malformed or
    oversized inbound messages, and answering heartbeats. All outbound
    traffic (match updates) is pushed independently by the pub/sub bridge
    via the ConnectionManager -- this loop only handles the client->server
    direction and dead-connection detection (a receive timeout tied to the
    heartbeat interval implies the client is gone)."""
    timeout = settings.websocket_heartbeat_seconds * 2
    while True:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
        if len(raw) > _MAX_MESSAGE_BYTES:
            logger.warning("Dropping oversized WebSocket message (%d bytes)", len(raw))
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            logger.warning("Dropping malformed (non-JSON) WebSocket message")
            continue
        if isinstance(message, dict) and message.get("type") == "PING":
            await websocket.send_json({"type": "PONG"})


async def _close_quietly(websocket: WebSocket, code: int) -> None:
    """A missed heartbeat or unexpected error should end in a real WS close
    frame, not an abrupt transport drop (client-visible as code 1006) --
    but the socket may already be half-closed by whatever we're reacting
    to, so this never raises."""
    try:
        await websocket.close(code=code)
    except Exception:
        pass


@router.websocket("/matches")
async def matches_ws(websocket: WebSocket) -> None:
    if not _origin_allowed(websocket) or manager.at_capacity(settings.websocket_max_connections):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect_general(websocket)
    try:
        await _receive_loop(websocket)
    except WebSocketDisconnect:
        pass
    except (TimeoutError, asyncio.TimeoutError):
        await _close_quietly(websocket, status.WS_1000_NORMAL_CLOSURE)
    except Exception:
        logger.exception("Unexpected error on /ws/matches")
        await _close_quietly(websocket, status.WS_1011_INTERNAL_ERROR)
    finally:
        manager.disconnect_general(websocket)


@router.websocket("/matches/{match_id}")
async def match_detail_ws(websocket: WebSocket, match_id: str) -> None:
    # Format-validated only (not checked against the database) -- but this
    # is what prevents a client from subscribing to an arbitrary string as
    # a "resource" (spec §29); match ids are internal auto-increment
    # integers, so anything else is rejected before a connection is ever
    # accepted.
    if not match_id.isdigit():
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not _origin_allowed(websocket) or manager.at_capacity(settings.websocket_max_connections):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect_match(websocket, match_id)
    try:
        await _receive_loop(websocket)
    except WebSocketDisconnect:
        pass
    except (TimeoutError, asyncio.TimeoutError):
        await _close_quietly(websocket, status.WS_1000_NORMAL_CLOSURE)
    except Exception:
        logger.exception("Unexpected error on /ws/matches/%s", match_id)
        await _close_quietly(websocket, status.WS_1011_INTERNAL_ERROR)
    finally:
        manager.disconnect_match(websocket, match_id)
