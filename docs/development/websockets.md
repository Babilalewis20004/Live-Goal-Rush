# WebSockets (Phase 2)

Full message contract, security model, and reconnection strategy are in
`architecture/realtime.md` — this doc is the practical "how do I work with
this" reference: endpoints, local testing, and where each piece of code
actually lives.

## Endpoints

| Path | Scope |
| --- | --- |
| `ws://<host>/ws/matches` | Every connected client, every match's updates |
| `ws://<host>/ws/matches/{match_id}` | Only that match's updates |

Mounted at the root (`/ws/...`), not under `/api/v1` — WebSocket endpoints
aren't REST resources and don't share that versioning scheme. Wired up in
`app/main.py::create_app()` (`app.include_router(websocket_router,
prefix="/ws")`).

## Code map

| File | Responsibility |
| --- | --- |
| `app/api/v1/websocket.py` | Route handlers — origin/capacity checks, the receive loop (heartbeat + inbound message validation), connect/disconnect wiring |
| `app/websocket/manager.py` | `ConnectionManager` — all connection state and broadcast logic, framework for "who's connected", independent of the transport |
| `app/websocket/pubsub_bridge.py` | Subscribes to Redis Pub/Sub, turns `RealtimeEvent`s into outbound WebSocket messages via the manager |
| `apps/web/lib/realtime.ts` / `apps/mobile/src/lib/realtime.ts` | Client-side connection (reconnect/backoff/heartbeat) |
| `apps/web/hooks/use-*.ts` / `apps/mobile/src/hooks/use-*.ts` | React (state) integration on top of the client |

## Local testing without a browser

With the API running (`uvicorn app.main:app --reload` or via Docker
Compose):

```bash
pip install websockets   # if not already available
python -c "
import asyncio, websockets
async def main():
    async with websockets.connect('ws://localhost:8000/ws/matches') as ws:
        async for message in ws:
            print(message)
asyncio.run(main())
"
```

You should see `MATCH_UPDATED`/`GOAL`/... JSON messages arrive on their
own as the worker's `sync_live_matches` task runs (every
`LIVE_POLL_INTERVAL_SECONDS`, 15s by default) — with the bundled mock
provider's simulated live progression (`realtime.md`), this requires no
manual trigger, just a running worker + scheduler.

For a match-scoped connection, connect to `ws://localhost:8000/ws/matches/{id}`
instead and confirm you only receive that match's updates.

## Automated tests

`apps/api/tests/test_websocket.py`, two layers:

- **Endpoint-level**, via FastAPI's `TestClient` (a real, synchronous ASGI
  WebSocket handshake): connect/disconnect state tracking, origin
  rejection, the connection cap, non-numeric `match_id` rejection, and the
  ping/pong heartbeat.
- **`ConnectionManager`-level**, via a fake WebSocket object (no ASGI):
  broadcast fan-out (general and match-scoped), dead-connection cleanup on
  a failed send, and match-entry cleanup on disconnect.

Neither layer touches Redis or `PubSubBridge` (which needs a live
`lifespan` to start) — `ConnectionManager` is deliberately a plain
in-process object with no Redis dependency, so it's fully unit-testable on
its own.

## Debugging a stuck/silent connection

1. `GET /health` — confirms Redis is reachable at all
   (`realtime.md`/`deployment/docker.md`).
2. Worker logs (`docker compose logs worker`) — `Match {id} changed: <TYPE>`
   lines confirm change detection is actually publishing something; if
   nothing's logged, either nothing changed (expected, most polls) or the
   provider/sync itself is failing (look for `ProviderUnavailableError` or
   a `sync_*: provider unavailable` line).
3. `WEBSOCKET_HEARTBEAT_SECONDS` — if a client seems to silently drop
   after ~2x this value with no visible error, it likely missed the
   server's receive timeout (dead-connection detection working as
   intended) — check the client is actually sending `{"type":"PING"}` on
   schedule.
