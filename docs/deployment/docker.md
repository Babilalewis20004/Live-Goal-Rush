# Docker (Phase 2)

## Services

```
┌───────────────────────────────────────────────────────────┐
│                          Docker                            │
│                                                              │
│  ┌───────┐    ┌──────────────┐                              │
│  │  Web  │───►│     API      │◄────────────┐                │
│  └───────┘    └──────┬───────┘              │                │
│                       │                      │                │
│                 ┌─────┴─────┐         ┌──────┴──────┐         │
│                 │ PostgreSQL │         │    Redis    │         │
│                 └─────┬─────┘         └──────┬──────┘         │
│                       │                      │                │
│                       │        ┌─────────────┴───────┐        │
│                       │        │                      │        │
│                    Worker ─────┘                  Scheduler    │
│                                                                 │
└───────────────────────────────────────────────────────────────┘
```

`api`, `worker`, and `scheduler` all build from the **same**
`apps/api/Dockerfile` — `worker`/`scheduler` just override the container
`command` (`docker-compose.yml`) to run Celery instead of Uvicorn. There is
one image, three processes, matching the spec's "keep the architecture
modular, don't over-engineer" guidance (no separate worker codebase, no
Kubernetes/Kafka/RabbitMQ).

## Bringing it up

```bash
cp .env.example .env   # override POSTGRES_PORT/REDIS_PORT if already taken
docker compose up --build
```

This builds and starts, in dependency order: `postgres` and `redis`
(health-checked), then `api` (runs `alembic upgrade head`, then serves —
also health-checked, see below), then `worker`/`scheduler`/`web` (which
wait for `api` to be healthy before starting).

| Service | URL / port |
| --- | --- |
| `api` | http://localhost:8000 (docs at `/docs`, health at `/health`, metrics at `/metrics`) |
| `web` | http://localhost:3000 |
| `postgres` | `localhost:${POSTGRES_PORT:-5432}` |
| `redis` | `localhost:${REDIS_PORT:-6379}` |
| `worker`, `scheduler` | no published port — internal only |

`apps/mobile` still isn't containerized (Expo/native tooling doesn't fit a
Compose service well, same as Phase 1) — run it locally
(`cd apps/mobile && npx expo start`), pointed at the Dockerized API via
`EXPO_PUBLIC_API_URL`/`EXPO_PUBLIC_WS_URL` (your machine's LAN IP, not
`localhost`, if testing on a physical device).

## Why `worker`/`scheduler` wait on `api`'s healthcheck, not just its start

`api`'s container command is `alembic upgrade head && uvicorn ...` —
migrations run before the server starts serving. `worker`/`scheduler`
query tables those migrations create (`standings`, `matches.last_synced_at`,
...) from their very first task. If they started as soon as the `api`
*container* started (Compose's `service_started` condition) rather than
once it's *healthy*, there's a real race: a worker task could run against
a schema that doesn't exist yet. `api`'s healthcheck
(`docker-compose.yml`) is a dependency-free Python `urllib` call to its
own `/health` endpoint — by the time that succeeds, migrations are
guaranteed complete, so `worker`/`scheduler` depend on `api: condition:
service_healthy`, not `service_started`.

## Environment variables

Every Phase 2 variable is documented with its default in
`apps/api/.env.example` (poll intervals, cache TTLs, WebSocket config,
retry/backoff, the mock provider's simulation speed) and summarized in the
root `.env.example`. All three of `api`/`worker`/`scheduler` receive the
same environment block in `docker-compose.yml` (a single YAML anchor,
`&api_env`) — they're the same application, so there's no reason for their
configuration to drift apart.

One variable is host/container-aware in a way worth calling out:
`NEXT_PUBLIC_WS_URL` / `EXPO_PUBLIC_WS_URL`. Every other `NEXT_PUBLIC_API_URL`
fetch in the web app runs **inside** the `web` container (Server
Components), so it resolves `http://api:8000` on the Docker network. The
WebSocket connection, though, is opened by the **browser**, on the host
machine — so it must resolve `ws://localhost:8000`, not the Docker-internal
hostname. `docker-compose.yml`'s `web` service sets these independently
for exactly this reason (see its inline comment).

## Health checks (spec §28)

`GET /health` reports each critical dependency independently rather than a
single always-`ok` status:

```json
{
  "status": "ok",
  "dependencies": { "api": "ok", "database": "ok", "redis": "ok", "provider": "ok" }
}
```

`200` when every dependency is healthy, `503` (with the same body, showing
which dependency is `"unavailable"`) otherwise — a degraded Postgres or
Redis is never reported as a healthy app. `provider` is a cheap
construction check (did `get_provider()` build successfully), not a live
network call on every health check — that would itself count against the
provider's own rate limit (`realtime.md`).

## Metrics (spec §27)

`GET /metrics` — Prometheus text format when `prometheus_client` is
installed (it's in `requirements.txt`), else a plain-text fallback of the
same counters. Per-process: the `api` process's `/metrics` reports its own
cache hit/miss and WebSocket counters; `provider_requests_total`/
`sync_jobs_total`/etc. are most meaningful read from the `worker`
process's logs today (see `app/services/metrics.py`'s docstring for why
cross-process aggregation isn't wired up — it would need Prometheus's
multiprocess mode, unnecessary complexity for Phase 2's scope; a Phase 3
candidate if a real metrics backend is introduced).

## Stopping / resetting

```bash
docker compose down          # stop, keep volumes (Postgres/Redis data persists)
docker compose down -v       # also drop postgres_data and redis_data
```
