"""WebSocket tests (Phase 2 §29/§30), split into two layers:

- Endpoint-level (via `TestClient`, a synchronous, real-ASGI-handshake
  client): connect/disconnect, origin validation, the connection cap, and
  the ping/pong heartbeat -- everything the route handlers
  (`app/api/v1/websocket.py`) are responsible for.
- `ConnectionManager`-level (fake WebSocket objects, no ASGI): broadcast
  fan-out, match-scoped subscriptions, and dead-connection cleanup --
  everything `app/websocket/manager.py` is responsible for, independent of
  the transport.

Neither layer touches Redis or the pub/sub bridge (which needs a live
lifespan) -- `manager` is a plain in-process object.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.security import create_access_token
from app.main import create_app
from app.websocket.manager import ConnectionManager, manager


@pytest.fixture
def ws_client() -> TestClient:
    return TestClient(create_app())


# -- endpoint-level (TestClient) --------------------------------------------


def test_general_endpoint_connects_and_tracks_state(ws_client):
    before = manager.connection_count()
    with ws_client.websocket_connect("/ws/matches"):
        assert manager.connection_count() == before + 1
    assert manager.connection_count() == before


def test_match_specific_endpoint_connects_and_tracks_state(ws_client):
    before = manager.connection_count()
    with ws_client.websocket_connect("/ws/matches/42"):
        assert manager.connection_count() == before + 1
        assert "42" in manager.match_connections
    assert manager.connection_count() == before
    assert "42" not in manager.match_connections


def test_non_numeric_match_id_is_rejected(ws_client):
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/ws/matches/not-a-number"):
            pass


def test_disallowed_origin_is_rejected(ws_client):
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/ws/matches", headers={"origin": "https://evil.example.com"}):
            pass


def test_allowed_origin_is_accepted(ws_client):
    allowed_origin = settings.cors_origin_list[0]
    with ws_client.websocket_connect("/ws/matches", headers={"origin": allowed_origin}):
        pass


def test_ping_receives_pong(ws_client):
    with ws_client.websocket_connect("/ws/matches") as ws:
        ws.send_json({"type": "PING"})
        assert ws.receive_json() == {"type": "PONG"}


def test_oversized_message_is_dropped_not_fatal(ws_client):
    with ws_client.websocket_connect("/ws/matches") as ws:
        ws.send_text("x" * 5000)
        ws.send_json({"type": "PING"})
        assert ws.receive_json() == {"type": "PONG"}


def test_valid_token_is_accepted(ws_client):
    """Phase 3 §5: the documented auth extension point actually does
    something now -- a valid token still just connects like anonymous."""
    token = create_access_token(user_id=1)
    with ws_client.websocket_connect(f"/ws/matches?token={token}"):
        pass


def test_valid_access_token_cookie_is_accepted(ws_client):
    """Web sends no query param at all -- the browser attaches the
    httpOnly `access_token` cookie to the WS handshake automatically,
    same as any other same-origin request."""
    token = create_access_token(user_id=1)
    ws_client.cookies.set("access_token", token)
    with ws_client.websocket_connect("/ws/matches"):
        pass


def test_invalid_token_is_rejected(ws_client):
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect("/ws/matches?token=not-a-real-token"):
            pass


def test_absent_token_behaves_exactly_as_before(ws_client):
    """No token -> anonymous connection, unchanged from Phase 2 -- the
    public real-time experience must not require auth."""
    before = manager.connection_count()
    with ws_client.websocket_connect("/ws/matches"):
        assert manager.connection_count() == before + 1
    assert manager.connection_count() == before


def test_connection_cap_is_enforced(ws_client, monkeypatch):
    monkeypatch.setattr(settings, "websocket_max_connections", manager.connection_count() + 1)
    with ws_client.websocket_connect("/ws/matches"):
        with pytest.raises(WebSocketDisconnect):
            with ws_client.websocket_connect("/ws/matches"):
                pass


# -- ConnectionManager-level (fake WebSocket, no ASGI) ----------------------


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail_on_send = False

    async def accept(self) -> None:
        pass

    async def send_json(self, message: dict) -> None:
        if self.fail_on_send:
            raise RuntimeError("connection closed")
        self.sent.append(message)


async def test_broadcast_general_reaches_all_general_connections():
    mgr = ConnectionManager()
    ws1, ws2 = _FakeWebSocket(), _FakeWebSocket()
    await mgr.connect_general(ws1)
    await mgr.connect_general(ws2)

    await mgr.broadcast_general({"type": "MATCH_UPDATED"})

    assert ws1.sent == [{"type": "MATCH_UPDATED"}]
    assert ws2.sent == [{"type": "MATCH_UPDATED"}]


async def test_broadcast_to_match_only_reaches_subscribers_of_that_match():
    mgr = ConnectionManager()
    subscriber, other = _FakeWebSocket(), _FakeWebSocket()
    await mgr.connect_match(subscriber, "123")
    await mgr.connect_match(other, "456")

    await mgr.broadcast_to_match("123", {"type": "GOAL"})

    assert subscriber.sent == [{"type": "GOAL"}]
    assert other.sent == []


async def test_dead_connection_is_cleaned_up_on_broadcast():
    mgr = ConnectionManager()
    dead = _FakeWebSocket()
    dead.fail_on_send = True
    await mgr.connect_general(dead)

    await mgr.broadcast_general({"type": "MATCH_UPDATED"})

    assert dead not in mgr.general_connections


async def test_disconnect_removes_match_entry_when_it_becomes_empty():
    mgr = ConnectionManager()
    ws = _FakeWebSocket()
    await mgr.connect_match(ws, "123")
    mgr.disconnect_match(ws, "123")
    assert "123" not in mgr.match_connections


def test_at_capacity():
    mgr = ConnectionManager()
    assert mgr.at_capacity(0) is True
    assert mgr.at_capacity(5) is False
