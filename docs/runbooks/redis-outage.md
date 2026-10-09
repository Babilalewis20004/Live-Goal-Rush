# Redis outage

**Symptoms.** `RedisUnreachableFromApi` / `RedisDown`; `/health/ready` → 503 with `"redis":"unavailable"`; slower pages;
live scores update on the next sync (≤ 30 s) instead of instantly; the worker logs broker connection errors.

**Impact (designed degradation, tested in `tests/test_degraded_dependencies.py`).**

| Feature | During the outage |
|---|---|
| Reading matches, teams, competitions, news, search, discovery | **works** — served from PostgreSQL (more load on the database) |
| Sign-in, registration, account pages, billing state | **works** — rate limits **fail open** so nobody is locked out |
| Comments, reactions, polls | work (counters rebuilt from Postgres) |
| Live push over WebSocket | paused; clients reconnect with backoff and re-fetch over REST, so they recover on their own |
| Celery (syncs, notifications, analytics) | queue unavailable: scheduled work stops; beat entries expire, so there is **no backlog avalanche** when it returns |
| Abuse protection | login / search / comment limits are off; nginx `limit_req` and bcrypt cost are the backstop |

## Diagnose

`$C ps redis`, `$C logs --tail 50 redis`, `docker compose … exec redis redis-cli -a "$REDIS_PASSWORD" info memory | grep -E "used_memory_human|maxmemory_human|evicted_keys"`.

* **Memory full with `noeviction`-like errors** (`OOM command not allowed`): the production overlay uses `volatile-lru`, which evicts only
  keys that have a TTL (caches, counters) — never the queue. If you see OOM anyway, something writes keys without TTLs:
  `redis-cli --scan --pattern 'football:*' | head` and check `ttl`.
* Container dead: `$C up -d redis` (AOF replays the queue and counters).

## Fix

`$C up -d redis` · raise `REDIS_MAXMEMORY` if `evicted_keys` climbs steadily · after a **flush or data loss**: nothing to restore
(caches repopulate; rate-limit windows reset; the Celery queue contents are re-created by the next beat ticks).

## Verify

`/health/ready` 200 → `GET /api/v1/admin/system` → `redis: ok`, `queue_length` draining → score updates arriving over
WebSocket (smoke test `ws` check).

## Afterwards

If the outage was OOM, review `docs/operations/redis.md` for the key families and their TTLs.
