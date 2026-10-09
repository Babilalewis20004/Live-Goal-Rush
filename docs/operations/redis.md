# Redis: what lives there, for how long, and what happens without it

Redis plays four roles: **cache** (cache-aside for hot reads), **counters** (rate limits, view dedup, engagement), **pub/sub**
(match events → WebSocket fan-out) and **Celery broker**. It holds nothing that cannot be recreated — Postgres is the system of record.

## Key families (audit, 2026-10-08)

| Key family | Purpose | TTL | Bounded by | Invalidation |
|---|---|---|---|---|
| `football:live`, `football:match:{id}` | live list, match detail | 30 s (`REDIS_LIVE_MATCH_TTL_SECONDS`) | #live matches | deleted by the sync task on every change |
| `football:matches:today`, `…:upcoming:{date}`, `football:competition:*`, `football:team:*`, standings, fixtures | slower-moving reads | 300 s (`REDIS_DEFAULT_TTL_SECONDS`) | #entities | TTL + sync-time deletes of affected keys |
| `football:match:{id}:{lineups,statistics,players,form,head-to-head}`, squads, players, profiles | near-immutable data | 3600 s (`REDIS_STATIC_TTL_SECONDS`); live matches use the live TTL | #matches/players | TTL |
| `football:match:{id}:state` | change-detection snapshot | **3 days** — added in Phase 7; it had **no TTL** and accumulated one key per match forever (`volatile-lru` would never have evicted it) | #tracked matches | refreshed by every sync |
| `football:articles:{version}:*`, `football:discovery:home:{version}`, `football:feed:user:{id}` | news/discovery/feed caches | 120 s / 120 s / 45 s | versioned: any content change bumps `football:articles:ver`, orphaning every old key, which then expire | version bump |
| `football:trending:*` | precomputed trending | 900 s | fixed set | recomputed by beat every 5 min |
| `football:search:suggest:*`, `football:search:popular:{day}` | suggestions, popular searches | short fixed TTLs | bounded by query-length and normalisation | TTL |
| `football:comments:*`, `football:reactions:*`, polls | community reads / counters | 30 s | #threads | bumped on write; rebuilt from Postgres if Redis forgets (tested) |
| `ratelimit:{bucket}:{identifier}` | fixed-window limiters | the window (10 s – 24 h) | one key per client per bucket per window; **now created with `INCR`+`EXPIRE NX` atomically** (Phase 7), so a counter can never persist without an expiry | TTL |
| `football:engagement:*` | view counters before they are folded into Postgres | counters 24 h; dedup markers 30 min; flush markers 24 h | bounded | folded into Postgres every minute |
| `football:sync-requested:*` | debounce of on-demand syncs | 1 h; per-minute budget keys 60 s | bounded | TTL |
| `football:metrics:*` | cross-process metric counters | counters persistent (a handful of keys); per-process gauges 90 s | O(#roles) | — |
| Celery queue `football` | broker list | none (a queue must not expire) | by consumption; `CeleryBacklog` alerts at 200 | consumed |
| `football:events` (channel) | pub/sub | n/a | n/a | n/a |

**Sensitive data.** No passwords, tokens, emails or payment data are stored. Per-user keys hold only user ids (rate limits, the personalised feed
cache, the content-notification daily cap). The viewer-specific parts of community responses are never cached (tested).

## Production configuration (`docker-compose.prod.yml`)

`--requirepass` · `--maxmemory 256mb` · `--maxmemory-policy volatile-lru` (evicts only keys that *have* a TTL — caches and counters — never the
queue or metric counters) · `--appendonly yes` (the queue and counters survive a restart). Not exposed on a host port. Monitored by `redis_exporter`.

## Behaviour when Redis is unavailable (tested — `tests/test_degraded_dependencies.py`, 33 tests)

* All public reads (matches, teams, competitions, articles, discovery, search, plans, polls, ads placements) return 200 from Postgres.
* Sign-in, registration and account use work; rate limiting fails **open** (accepted risk S-24; nginx limits remain).
* Billing state and entitlements do not touch Redis.
* `/health/ready` → 503 (`redis: unavailable`) while `/health/live` stays 200; `/metrics` falls back to process-local counters.
* WebSocket fan-out and the Celery queue pause; beat entries expire rather than queueing, so recovery is not a stampede.
* When Redis returns everything resumes without a restart (the clients reconnect).

## Memory sizing

Measured with the synthetic dataset (20 k users, 3 k articles, 440 k comments) after a full load run: **≈ 3 MB** used, 30–45 clients. The 256 MB cap
therefore has two orders of magnitude of headroom for caches; the realistic risk is the queue, not the caches.
