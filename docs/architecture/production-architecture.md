# Production architecture (Phase 7)

The architecture is unchanged from Phases 1-6: **Next.js + Expo → FastAPI → PostgreSQL / Redis / Celery**, plus
WebSockets. Phase 7 adds the pieces that make that safe to run for real users: a reverse proxy, production
configuration validation, health/readiness probes, an operations API, and the backup and deployment tooling around it.
Nothing was added that the load tests did not call for (no Kubernetes, message broker swap, search engine or service
split — see "What was deliberately not added").

```
                       Internet
                          │   TLS terminated here: cloud load balancer, Caddy or Cloudflare
                          ▼
              ┌──────────────────────────┐
              │ nginx (unprivileged)     │  deploy/nginx/nginx.conf
              │  · single public origin  │  · request size caps, coarse rate limits, gzip
              │  · /metrics is not routed│  · X-Request-ID minted here and passed down
              └─────────┬────────────────┘  · overwrites X-Forwarded-For (never appends)
                        │
          ┌─────────────┴───────────────┐
          │  /api/*  /ws/*  /health/*   │   everything else
          ▼                             ▼
   ┌─────────────┐               ┌─────────────┐
   │ FastAPI     │               │ Next.js web │  CSP with per-request nonce (apps/web/proxy.ts)
   │ uvicorn     │               │ (SSR)       │  server calls the API over the private network
   │ × N workers │               └─────────────┘
   └──┬───┬───┬──┘
      │   │   └──────────────► WebSocket manager (per process) ◄── Redis pub/sub bridge
      │   │
      ▼   ▼
 PostgreSQL  Redis ◄──────────── Celery broker/queue, caches, rate-limit counters, pub/sub
      ▲       ▲
      └───┬───┘
          │
   ┌──────┴────────┐
   │ Celery worker │  sync, analytics, predictions, notifications, housekeeping   (same image as the API)
   │ Celery beat   │  schedule with per-entry expiry; one instance only
   └───────────────┘
```

Mobile (Expo) talks to the same public origin as the web app and holds a WebSocket to `/ws/*`.

## Components and how each one scales

| Component | Runs as | Stateless? | Scale by | Limit to watch |
|---|---|---|---|---|
| nginx | 1 container | yes | add instances behind the load balancer | worker connections (4096) |
| Web (Next.js) | 1+ containers | yes | replicas | CPU (SSR) |
| API (FastAPI) | `WEB_CONCURRENCY` uvicorn workers per container, 1+ containers | yes — except WebSocket sockets, which live in the process that accepted them | workers per container, then containers | CPU per process; DB connections = (pool + overflow) × workers |
| WebSocket layer | inside the API processes | per-process connection set; fan-out via Redis pub/sub so any process can serve any client | more API workers/containers | `WEBSOCKET_MAX_CONNECTIONS` (per process), `WEBSOCKET_MAX_CONNECTIONS_PER_IP` |
| Celery worker | 1+ containers (`--concurrency`) | yes (tasks are idempotent) | containers / concurrency | queue depth, provider rate limit |
| Celery beat | exactly 1 | n/a | do not scale | — |
| PostgreSQL | 1 primary | no | vertical first; read replica only if measurements demand it | `max_connections`, I/O |
| Redis | 1 instance, password, 256 MB, `volatile-lru`, AOF | no | vertical | memory, never evicts the queue |

`docs/operations/capacity.md` gives the numbers behind these limits and the thresholds at which each should be scaled.

## Request path and where each protection sits

1. **nginx** — body ≤ 1 MB (7 MB for image uploads), `limit_req` on `/api/v1/auth/` and `/api/`, 50 sockets/IP on `/ws/`,
   `X-Request-ID` generated, `X-Forwarded-For` replaced with the peer address, JSON access log with that request id.
2. **API middleware** (outermost first) — security headers + `Cache-Control: no-store` on credentialed paths →
   body-size limit (413 before a handler runs) → trusted-host check (when `ALLOWED_HOSTS` is set) → CORS →
   request-id / metrics / structured log line (with `user_id` once authenticated).
3. **Dependencies** — rate limiters (Redis, fail-open for ordinary traffic), then authentication (`CurrentUserDep`
   re-reads the user from Postgres every request, so suspension is immediate), then authorization (role dependency
   *before* body validation) and entitlement checks (`EntitlementsDep`, computed from the database per request).
4. **Handlers → services** — reads come from Redis cache-aside, falling back to Postgres; **reads never call the
   football provider** (the one exception is bootstrapping a brand-new empty database).
5. **Celery** — tasks carry the originating `request_id`; failures are classified, retried with backoff only when
   temporary, and recorded in `failed_jobs` when they finally fail.

## Failure behaviour (summary — details in `docs/operations/failure-modes.md`)

| Dependency down | What users see | What happens |
|---|---|---|
| Redis | everything still works from Postgres, slower; live scores update on the next sync instead of instantly | caches and rate limits fail open, `/health/ready` → 503, WebSocket fan-out pauses and resumes on reconnect |
| PostgreSQL | API answers 503 + `Retry-After`; clients retry | pooled connections are re-validated (`pool_pre_ping`), service recovers without a restart |
| Football provider | stored data keeps being served, marked `STALE` | sync tasks back off; the `FootballLiveDataStale` alert fires |
| Celery worker | no new syncs/notifications; reads unaffected | beat entries expire instead of queueing a backlog |
| API instance | the proxy routes to another instance; WebSocket clients reconnect with backoff and re-fetch | — |

## What was deliberately not added

Kubernetes, Kafka/RabbitMQ, Elasticsearch/OpenSearch, a service mesh or additional microservices. The measurements in
`docs/operations/load-testing.md` show the limiting factor is CPU per Python process, which uvicorn workers and API
replicas address directly. The triggers that would justify revisiting this are listed in "Phase 8 recommendation" in the
Phase 7 report.
