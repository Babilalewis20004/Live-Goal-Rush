"""WebSocket recovery check: do connected clients get live events again after Redis (or the API) goes away and comes back?

    python load/ws_recovery.py redis            # stop Redis for 20 s, then publish events until a client receives one
    python load/ws_recovery.py api              # restart the API container; the client reconnects like the apps do

Prints the seconds from "the dependency is back" until the first event arrives. Uses the compose project in the current
directory and the dev Redis (no password). Reconnect logic for the `api` mode mirrors the apps' RealtimeConnection:
exponential backoff from 1 s, capped at 30 s.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time

import websockets

BASE = "ws://127.0.0.1:8000/ws/matches"
EVENT = json.dumps({"type": "GOAL", "match_id": "1", "data": {"home_score": 1, "away_score": 0, "status": "live", "minute": 5}})


def docker(*args: str) -> None:
    subprocess.run(["docker", *args], capture_output=True, check=False)


def publish() -> None:
    docker("exec", "live-goal-redis-1", "redis-cli", "publish", "football:events", EVENT)


async def redis_mode() -> None:
    async with websockets.connect(BASE, origin="http://localhost:3000") as ws:
        print("connected; stopping Redis for 20 s", flush=True)
        docker("stop", "live-goal-redis-1")
        await asyncio.sleep(20)
        still_open = ws.state.name == "OPEN"
        await ws.send(json.dumps({"type": "PING"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(f"after 20 s without Redis: socket still open={still_open}, heartbeat answered={pong.get('type') == 'PONG'}", flush=True)
        docker("start", "live-goal-redis-1")
        back = time.monotonic()
        print("Redis started; publishing until the client receives an event", flush=True)
        while time.monotonic() - back < 90:
            publish()
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.5))
            except asyncio.TimeoutError:
                continue
            if message.get("type") == "GOAL":
                print(f"event received {time.monotonic() - back:.1f} s after Redis was started (the server-side bridge resubscribed on its own)", flush=True)
                return
        print("NO EVENT RECEIVED within 90 s", flush=True)
        sys.exit(1)


async def api_mode() -> None:
    delay, attempts, started_restart = 1.0, 0, None
    loop = asyncio.get_running_loop()
    ws = await websockets.connect(BASE, origin="http://localhost:3000")
    print("connected; restarting the API container", flush=True)
    restart = loop.run_in_executor(None, lambda: docker("restart", "live-goal-api-1"))
    started_restart = time.monotonic()
    try:
        await ws.recv()
    except websockets.ConnectionClosed:
        print(f"socket closed {time.monotonic() - started_restart:.1f} s after the restart began; reconnecting with backoff", flush=True)
    await restart
    while True:
        attempts += 1
        try:
            ws = await websockets.connect(BASE, origin="http://localhost:3000", open_timeout=2)
            await ws.send(json.dumps({"type": "PING"}))
            await asyncio.wait_for(ws.recv(), timeout=2)
            print(f"reconnected after {attempts} attempt(s), {time.monotonic() - started_restart:.1f} s after the restart began", flush=True)
            publish()
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print(f"live event delivered over the new socket: {message.get('type')}", flush=True)
            return
        except Exception:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


asyncio.run(redis_mode() if sys.argv[1:] == ["redis"] else api_mode())
