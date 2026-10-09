# WebSocket (live updates) problems

**Symptoms.** Web/mobile show "Reconnecting…"/"Offline"; scores only change on refresh; `WebSocketClientsBeingEvicted`.

**Impact.** Clients fall back to what the REST API serves; the **mobile app and web show how old the data is** and re-fetch on
reconnect, so no one is shown frozen scores as if they were live. Nothing is lost server-side.

## How it is built (what to expect)

Worker publishes events to Redis pub/sub → every API process receives them (`PubSubBridge`) → each fans out to *its* sockets.
Each process caps total sockets (`WEBSOCKET_MAX_CONNECTIONS`, default 1000), sockets per client address
(`WEBSOCKET_MAX_CONNECTIONS_PER_IP`, 25), and gives each send `WEBSOCKET_SEND_TIMEOUT_SECONDS` (5 s): a client that stops reading is
disconnected (code 1013) instead of delaying everyone else. Heartbeat: clients ping every 30 s; the server drops a socket that
is silent for 60 s. Disconnects always remove the socket from the manager (tested; no leak).

## Diagnose

1. `docker compose exec api python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"` (nginx blocks `/metrics`; it is internal only) → `websocket_connections`, `websocket_clients_evicted_total`, `websocket_disconnections_total`.
2. Handshake test: `python apps/api/scripts/smoke.py --base https://<site>` (the `ws:` check opens a socket and exchanges PING/PONG).
3. Through the proxy only? nginx must pass `Upgrade`/`Connection` and have `proxy_read_timeout` ≥ 75 s for `/ws/` (it does, in `deploy/nginx/nginx.conf`).
   A load balancer in front needs an idle timeout above 75 s and WebSocket support enabled.
4. All clients refused with 1008: origin not in `CORS_ORIGINS`, or capacity reached (`websocket_connections` ≈ the cap) — or one address
   hitting `WEBSOCKET_MAX_CONNECTIONS_PER_IP` (corporate NAT/proxy: raise it, or trust the proxy's forwarded address via `TRUSTED_PROXY_CIDRS`).
5. Connected but no updates: Redis pub/sub down ([redis-outage.md](redis-outage.md)) or the worker not syncing ([celery-backlog.md](celery-backlog.md)).

## Fix

| Cause | Action |
|---|---|
| Capacity | raise `WEBSOCKET_MAX_CONNECTIONS` (memory is ~50 KB/socket) and add API workers; sockets spread across processes |
| One address over its share | raise `WEBSOCKET_MAX_CONNECTIONS_PER_IP`, or fix `TRUSTED_PROXY_CIDRS` so the visitor, not the proxy, is counted |
| Proxy/LB dropping idle sockets | idle timeout > 75 s |
| API restart | clients reconnect with exponential backoff (1 s → 30 s) and refresh over REST first; nothing to do |
