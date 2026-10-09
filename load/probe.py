"""Poll a few endpoints twice a second and print a timeline of status changes -- used while breaking things on purpose.

    python load/probe.py --base http://127.0.0.1:8000 --seconds 90 --label postgres-stop

Prints one line each time any endpoint's answer changes, with seconds since the start, so "the API went 503 at t=3.1 s
and was healthy again at t=9.6 s" can be read off directly. Endpoints: liveness, readiness, a cached read, an uncached read
(competition standings), a search, and a WebSocket ping.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx

PATHS = {
    "live": "/health/live",
    "ready": "/health/ready",
    "matches": "/api/v1/matches/upcoming",
    "standings": "/api/v1/competitions/1/standings",
    "search": "/api/v1/search?q=arsen",
}


async def ws_ping(base: str) -> str:
    import websockets

    try:
        async with websockets.connect(base.replace("http", "ws", 1) + "/ws/matches", origin="http://localhost:3000", open_timeout=2) as ws:
            await ws.send(json.dumps({"type": "PING"}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            return "ok" if reply.get("type") == "PONG" else "bad"
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    started = time.monotonic()
    last: dict[str, str] = {}
    worst: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=4) as client:
        while time.monotonic() - started < args.seconds:
            t = time.monotonic() - started
            row: dict[str, str] = {}
            for name, path in PATHS.items():
                t0 = time.monotonic()
                try:
                    r = await client.get(args.base + path)
                    row[name] = str(r.status_code)
                except httpx.HTTPError as exc:
                    row[name] = type(exc).__name__
                worst[name] = max(worst.get(name, 0), time.monotonic() - t0)
            row["ws"] = await ws_ping(args.base)
            if row != last:
                print(f"[{args.label}] t={t:6.1f}s  " + "  ".join(f"{k}={v}" for k, v in row.items()), flush=True)
                last = row
            await asyncio.sleep(0.4)
    print(f"[{args.label}] done; slowest single answer per endpoint: " + ", ".join(f"{k}={v:.2f}s" for k, v in worst.items()))


asyncio.run(main())
