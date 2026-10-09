"""WebSocket fan-out check: N sockets watch one match; one comment is posted; how long until all N get the nudge?

    python scripts/ws_fanout.py --base http://localhost:8000 --sockets 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx


async def main() -> None:
    import websockets

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--sockets", type=int, default=100)
    args = parser.parse_args()
    api = f"{args.base}/api/v1"
    ws_base = args.base.replace("http", "ws", 1)

    async with httpx.AsyncClient(timeout=30) as c:
        match_id = ((await c.get(f"{api}/matches/today")).json() + (await c.get(f"{api}/matches/upcoming")).json())[0]["id"]
        email = f"fanout{int(time.time())}@example.com"
        reg = await c.post(f"{api}/auth/register", json={"email": email, "password": "Sup3rSecret!", "password_confirm": "Sup3rSecret!"}, headers={"X-Client": "mobile"})
        headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

        received: list[float] = []

        async def listen(ws) -> None:
            while True:
                message = json.loads(await ws.recv())
                if message.get("type") == "comment.created":
                    received.append(time.perf_counter())
                    return

        sockets = [await websockets.connect(f"{ws_base}/ws/matches/{match_id}", origin="http://localhost:3000") for _ in range(args.sockets)]
        listeners = [asyncio.create_task(listen(ws)) for ws in sockets]
        await asyncio.sleep(0.5)
        sent = time.perf_counter()
        r = await c.post(f"{api}/comments", json={"target_type": "match", "target_id": match_id, "body": f"fan-out check {int(sent)}"}, headers=headers)
        assert r.status_code == 201, r.text
        done, pending = await asyncio.wait(listeners, timeout=10)
        for task in pending:
            task.cancel()
        for ws in sockets:
            await ws.close()
        latencies = sorted((t - sent) * 1000 for t in received)
        print(f"{len(received)}/{args.sockets} sockets received the nudge; "
              f"first {latencies[0]:.0f} ms, median {latencies[len(latencies) // 2]:.0f} ms, last {latencies[-1]:.0f} ms" if latencies else "no messages received")


if __name__ == "__main__":
    asyncio.run(main())
