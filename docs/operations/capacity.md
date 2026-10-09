# Capacity, scaling and the numbers to watch

How the current architecture scales **without adding infrastructure**, and the measured thresholds at which each component should be scaled. Evidence: `docs/operations/load-testing.md`
(development hardware, 4 vCPU shared with the load generator). Re-derive the thresholds from a staging run on production-class hardware before relying on the absolute figures.

## What limits what (measured)

| Component | Limiting resource | Measured | Scale by |
|---|---|---|---|
| **API process** (one uvicorn worker) | **CPU: one core** | saturates at ≈ 0.9 core. Capacity ≈ **340 req/s** for a no-dependency request, **≈ 190** for a Redis-cached read, **≈ 105** for a cached search, **≈ 75** for an uncached search, **≈ 40–55 req/s** for realistic mixed browsing with some cold keys | more uvicorn workers (`WEB_CONCURRENCY`, one per core), then more containers behind nginx. Three workers raised a 400-user surge from 67 to 106 req/s with the errors going 45 → 0 |
| **WebSocket layer** | memory + one socket per client | ≈ **40 KB per connection** (1,000 held sockets: API RAM 154 → 197 MB); connect p99 148 ms; 0 dropped. Default cap 1,000 per process (`WEBSOCKET_MAX_CONNECTIONS`), 25 per address | cap and workers; every process serves any client, events fan out through Redis pub/sub |
| **PostgreSQL** | connections, then I/O | **never the bottleneck**: ≤ 0.25 core, ≤ 4 active connections in every run, including 400 virtual users. 44 connections open at 3 workers | `max_connections`; a read replica only if CPU > 70 % sustained (not expected before 10× this load) |
| **Redis** | memory (tiny), single-threaded CPU | 2–5 MB, 25–69 clients, queue empty. 256 MB cap = ≥ 50× headroom | vertical |
| **Celery worker** | provider quota, then CPU | periodic jobs 0.01–2 s each on 440 k comments; 0.15–0.4 core average; fan-out of a goal to 9,076 followers ≈ 6 s of database work | `--concurrency`, more containers; beat stays single |
| **Web (Next.js)** | CPU (server rendering) | not load-tested separately; every page is rendered on demand (live data) | replicas |

## Connection arithmetic (the thing that bites first when scaling)

`connections ≈ (DB_POOL_SIZE + DB_MAX_OVERFLOW) × (API workers × API containers + Celery processes)` at worst; typical use is far lower (measured 5–44).
Defaults 10 + 10 per process: 3 workers + 2 Celery processes → up to 100 = Postgres' default `max_connections`. When you pass ≈ 70 % of it, either lower the pools (they are generous: peak use was 4 active),
raise `max_connections`, or put PgBouncer (transaction mode) in front. A request that cannot get a connection within 10 s fails with 503 + `Retry-After` (`db_pool_exhausted_total`).

## Scaling thresholds

| Signal | Threshold | Action |
|---|---|---|
| API CPU per worker (container CPU ÷ workers) | avg > **0.7 core for 10 min** | add a worker/replica — a worker is near saturation at 0.9 |
| API latency | p95 > **1 s** for 10 min (`SlowRequests`) or p99 > **3 s** (`ApiLatencyP99High`) | same; if CPU is low, look at the database (`pg_stat_statements`) |
| 503s from pool exhaustion | any sustained (`DatabaseConnectionPoolExhausted`) | add API capacity first (connections are held longer when the loop is CPU-bound), then revisit pool sizes |
| WebSocket connections per process | > **70 %** of `WEBSOCKET_MAX_CONNECTIONS` | add workers/replicas; eviction rate > 1/s means clients can't keep up (network or bug) |
| Celery queue length | > **200** for 10 min (`CeleryBacklog`) | raise `--concurrency` / add a worker; check the provider isn't throttling |
| Dead letters | > **20** unresolved (`FailedJobsNeedAttention`) | triage (`docs/runbooks/celery-backlog.md`) |
| Live-data age | > **300 s** while a match is live (`FootballLiveDataStale`) | provider/worker problem, not capacity |
| PostgreSQL connections | > **70 %** of `max_connections` | see above |
| PostgreSQL CPU / active connections | CPU > 70 % for 15 min, or active connections consistently ≈ cores | investigate queries; vertical scale; consider a replica for read-heavy endpoints |
| Redis memory | > **70 %** of `maxmemory`, or `evicted_keys` rising | raise `REDIS_MAXMEMORY`; check for keys without TTLs (`redis-cli --scan`) |
| Web container CPU | avg > 70 % | add replicas |

## How to scale each part (no new technology)

1. **Web** — `docker compose … up -d --scale web=N`; nginx upstream lists the instances (use a compose service name that resolves to all replicas, or list them).
2. **API** — raise `WEB_CONCURRENCY` (one worker per core). Beyond one host, run the same compose stack on several hosts behind the load balancer; migrations once (`RUN_MIGRATIONS=0` on replicas).
   Sessions are stateless (JWT + DB); WebSocket clients may land on any instance.
3. **Workers** — `--scale worker=N` or `CELERY_CONCURRENCY`; tasks are idempotent. Keep exactly **one** `scheduler` (beat); two would double every periodic job (the dedup ledgers make duplicates harmless, but wasteful).
4. **Database** — vertical; read replica later (reads that tolerate seconds of lag: news, team and competition pages); partition `notification_log`/`engagement_buckets` by time if they pass ≈ 50 M rows.
5. **Redis** — vertical; Sentinel/managed Redis for HA if the queue's availability matters more than a few minutes of delayed syncs (it currently does not).

## Turning requests per second into users (a method, not a promise)

Measure your own ratio, then divide: `concurrent users ≈ requests/s × average seconds between a user's requests`. In the tests a "home" virtual user made one 4-call page view every ≈ 2 s of think time and
the server sustained ≈ 39 req/s of that per worker at p95 316 ms — i.e. about **10 page views per second per worker**, which at 2 s think time is ~25 simultaneously active visitors per worker for that scenario; scale that
by the cache hit rate and traffic mix you actually have. These are 4-vCPU development-VM figures with the load generator on the same machine; production sizing must come from a staging run (`load/run-suite.sh`).
