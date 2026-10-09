"""WebSocket resource protection (Phase 7 §13): slow clients, per-address caps, leak-free disconnects."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.main import create_app
from app.websocket.manager import ConnectionManager, manager


class FakeSocket:
    """Stands in for a Starlette WebSocket; `send_delay` models a client that stopped reading."""

    def __init__(self, send_delay: float = 0.0, fail: bool = False):
        self.send_delay, self.fail = send_delay, fail
        self.received: list[dict] = []
        self.accepted = False
        self.closed_with: int | None = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.fail:
            raise ConnectionResetError("peer went away")
        if self.send_delay:
            await asyncio.sleep(self.send_delay)
        self.received.append(message)

    async def close(self, code=1000):
        self.closed_with = code


async def test_one_stalled_client_does_not_delay_everyone_else(monkeypatch):
    monkeypatch.setattr(settings, "websocket_send_timeout_seconds", 0.3)
    mgr = ConnectionManager()
    healthy = [FakeSocket() for _ in range(5)]
    stalled = FakeSocket(send_delay=30)  # a phone that lost signal without closing the socket
    for ws in [stalled, *healthy]:
        await mgr.connect_general(ws)

    started = asyncio.get_running_loop().time()
    await mgr.broadcast_general({"type": "score", "n": 1})
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 1.5  # bounded by the send timeout, not by the stalled client's 30 s
    assert all(ws.received == [{"type": "score", "n": 1}] for ws in healthy)
    assert stalled.received == []


async def test_a_client_that_cannot_receive_is_evicted_and_its_resources_released(monkeypatch):
    monkeypatch.setattr(settings, "websocket_send_timeout_seconds", 0.2)
    mgr = ConnectionManager()
    stalled, broken, fine = FakeSocket(send_delay=10), FakeSocket(fail=True), FakeSocket()
    await mgr.connect_general(stalled, "10.0.0.1")
    await mgr.connect_match(broken, "7", "10.0.0.2")
    await mgr.connect_match(fine, "7", "10.0.0.3")

    await mgr.broadcast_general({"type": "x"})
    await mgr.broadcast_to_match("7", {"type": "y"})
    await asyncio.sleep(0.05)  # let the fire-and-forget close run

    assert mgr.connection_count() == 1
    assert fine in mgr.match_connections["7"]
    assert stalled.closed_with == 1013 and broken.closed_with == 1013
    assert mgr.ip_at_capacity("10.0.0.1", 1) is False  # its slot in the per-address count was released too


async def test_connections_are_counted_per_address_and_released_on_disconnect():
    mgr = ConnectionManager()
    sockets = [FakeSocket() for _ in range(3)]
    for ws in sockets:
        await mgr.connect_general(ws, "203.0.113.5")
    assert mgr.ip_at_capacity("203.0.113.5", 3)
    assert not mgr.ip_at_capacity("203.0.113.5", 4)
    assert not mgr.ip_at_capacity("203.0.113.6", 3)
    assert not mgr.ip_at_capacity("203.0.113.5", 0)  # 0 = unlimited
    for ws in sockets:
        mgr.disconnect_general(ws)
    assert not mgr.ip_at_capacity("203.0.113.5", 1)
    assert mgr._per_ip == {} and mgr._ip_of == {}  # nothing left behind


async def test_disconnecting_twice_does_not_corrupt_the_counts():
    mgr = ConnectionManager()
    ws = FakeSocket()
    await mgr.connect_match(ws, "1", "198.51.100.1")
    mgr.disconnect_match(ws, "1")
    mgr.disconnect_match(ws, "1")
    assert mgr.connection_count() == 0 and mgr._per_ip == {}


def test_an_address_over_its_share_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "websocket_max_connections_per_ip", 2)
    client = TestClient(create_app())
    with client.websocket_connect("/ws/matches"), client.websocket_connect("/ws/matches"):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect("/ws/matches"):
                pass
        assert refused.value.code == 1008
    # the budget is returned when the sockets close
    with client.websocket_connect("/ws/matches"):
        pass
    assert manager._per_ip.get("testclient", 0) == 0


def test_an_abrupt_disconnect_leaves_nothing_behind():
    client = TestClient(create_app())
    before = manager.connection_count()
    ws = client.websocket_connect("/ws/matches/99")
    session = ws.__enter__()
    assert manager.connection_count() == before + 1
    session.close()  # no clean goodbye handshake from the app's side
    ws.__exit__(None, None, None)
    assert manager.connection_count() == before
    assert "99" not in manager.match_connections


def test_the_per_address_cap_honours_a_trusted_proxys_forwarded_address(monkeypatch):
    monkeypatch.setattr(settings, "websocket_max_connections_per_ip", 1)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8,testclient")  # not an IP: ignored, so no trust
    client = TestClient(create_app())
    with client.websocket_connect("/ws/matches", headers={"x-forwarded-for": "1.1.1.1"}):
        # a spoofed header from an untrusted peer must not buy a second slot
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/matches", headers={"x-forwarded-for": "2.2.2.2"}):
                pass
