# Caching (Phase 2)

Redis sits in front of Postgres as a cache-aside layer for high-read
football data. **Redis is never the source of truth** — Postgres is; a
Redis outage degrades response times (falls back to a database read), it
does not make data unavailable. See `app/services/cache.py`'s docstring
and `system-architecture.md`'s "Database vs. Redis" section.

## Cache-aside pattern

```
Client
  │
  ▼
FastAPI (FootballService read method)
  │
  ▼
Redis
  │
  ├── HIT ──► deserialize into the Pydantic response model, return
  │
  └── MISS
        │
        ▼
    PostgreSQL (never the provider — see realtime.md)
        │
        ▼
      Redis (populate, with a TTL)
        │
        ▼
      Client
```

Implemented once, generically, in `app/services/cache.py::CacheAside`
(`get_or_set_model` / `get_or_set_list`), used by
`app/services/football_service.py`'s read methods rather than each one
reimplementing the hit/miss/populate dance. If Redis itself is
unreachable, `CacheAside` catches the error, logs a warning, and calls the
loader directly — see "Redis outages" below.

## Key namespace

All keys are built by `app/core/redis_keys.py::RedisKeys` — nothing else
in the codebase hand-types a Redis key string.

| Key | Data | TTL |
| --- | --- | --- |
| `football:live` | `/matches/live` result | `REDIS_LIVE_MATCH_TTL_SECONDS` (30s default) |
| `football:matches:today` | `/matches/today` result | `REDIS_DEFAULT_TTL_SECONDS` (300s default) |
| `football:matches:upcoming:{date}` | `/matches/upcoming` result, keyed by today's date | `REDIS_DEFAULT_TTL_SECONDS` |
| `football:match:{id}` | `/matches/{id}` full detail (includes its events — see below) | `REDIS_LIVE_MATCH_TTL_SECONDS` |
| `football:match:{id}:state` | Change detection's last-published snapshot (score/status/minute/event ids) | none — overwritten every sync, not a response cache |
| `football:competition:{id}:fixtures:{date}` | `/competitions/{id}/fixtures` result | `REDIS_DEFAULT_TTL_SECONDS` |
| `football:competition:{id}:standings` | `/competitions/{id}/standings` result | `REDIS_DEFAULT_TTL_SECONDS` |
| `football:team:{id}:fixtures` | Both `/teams/{id}/fixtures` and `/teams/{id}/results` (filtered client-side from one cached list — see below) | `REDIS_DEFAULT_TTL_SECONDS` |
| `football:competitions` | `/competitions` list (not in the spec's minimum cache list, but cheap and near-static — see below) | `REDIS_DEFAULT_TTL_SECONDS` |
| `football:events` | Not a cache entry — the Pub/Sub channel the worker publishes `RealtimeEvent`s to (see realtime.md) | n/a |

**`/matches/{id}/events` deliberately has no separate
`football:match:{id}:events` cache entry**, even though it's in the
spec's example key list — `MatchDetail` (cached under `football:match:{id}`)
already embeds the full event list, they're always synced together, and a
second cache entry would only ever hold the same data with its own TTL to
keep track of. `FootballService.get_match_events` reads it off the
already-cached `get_match` result instead.

**`/teams/{id}/fixtures` and `/teams/{id}/results`** share one cache
entry (all of a team's matches, unfiltered) because the only difference
between the two endpoints is a `status` filter applied in Python
(`football_service.get_team_fixtures`) — caching the unfiltered list once
and filtering on every read is cheaper than maintaining two overlapping
cache entries that would need to be invalidated together anyway.

## TTL strategy

Two tiers, both configurable via env vars (`.env.example`), not hard-coded
per call site:

- **`REDIS_LIVE_MATCH_TTL_SECONDS` (default 30s)** — live matches, match
  detail, match events. Deliberately close to `LIVE_POLL_INTERVAL_SECONDS`
  (15s default) — around 2x it — so a cache entry never meaningfully
  outlives the sync cycle that would have refreshed it, without expiring
  faster than new data could possibly arrive anyway. In practice this
  barely matters for freshness — the worker explicitly invalidates
  `football:match:{id}` and `football:live` the moment change detection
  publishes a real change (`app/worker/tasks.py::_publish_changes`), so
  the TTL is a safety net for "nothing changed, but let's not cache
  forever," not the primary freshness mechanism.
- **`REDIS_DEFAULT_TTL_SECONDS` (default 300s)** — today/upcoming
  fixtures, standings, team fixtures. These change far less often
  (fixtures sync runs every 5+ minutes — see
  `development/background-workers.md`), so a longer TTL is safe and cuts
  database load without serving noticeably stale data.

Do **not** raise `REDIS_LIVE_MATCH_TTL_SECONDS` to match the slower tier —
a long TTL on live data is explicitly called out as a mistake to avoid
(spec §4): a stuck-for-5-minutes cache entry on a match that's actually
still progressing would look like the app stopped working, not like a
mild bit of staleness.

## Cache invalidation

Besides TTL expiry, the worker actively invalidates on a real change so
clients don't have to wait out the TTL to see it:
`app/worker/tasks.py::_publish_changes` deletes `football:match:{id}` and
`football:live` (and `football:matches:today`) right after publishing a
change-detection event. This is best-effort, not required for
correctness — the TTL alone guarantees eventual consistency — it just
makes the REST fallback (a client that reconnects and re-fetches instead
of relying purely on the WebSocket push) feel as fresh as the WebSocket
push it's paired with.

## Redis outages

`CacheAside` (and the lower-level `RedisService`) catch every Redis
operation's exceptions and fall back to calling the loader (i.e. reading
Postgres) directly, logging a warning rather than raising. A Redis outage
therefore degrades to "every request does a database read instead of a
cache hit" — slower, not broken. This mirrors the provider-failure
handling principle in `realtime.md` applied to the cache layer instead of
the provider.

## `/competitions`: a deliberate exception

Spec §4's minimum cache list doesn't include the plain competition list
(`GET /competitions`), and it's small/near-static (six rows for the
bundled mock dataset). Rather than leave it uncached (a provider call on
every request) or invent a dedicated sync job just for six rows, it's
cache-aside like everything else, straight against the provider on a
miss, under `football:competitions` with the default TTL. This is the one
read path that can still reach the provider directly — everywhere else,
reads only ever reach Postgres (see `realtime.md`).
