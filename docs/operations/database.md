# Database review (PostgreSQL)

Method: a database with realistic volume (`apps/api/scripts/seed_volume.py`, scale 1: **20,000 users, 3,000 articles, 440,000 comments,
60,000 reactions, 609,000 notification-ledger rows, 80,000 sessions, 50,000 payment events, 60,000 favourites**, on top of the real
1,140 matches / 67 teams / 1,672 players synced from the provider; 304 MB), `pg_stat_statements` + `track_io_timing` enabled, the load
scenarios run through the real API, then `EXPLAIN (ANALYZE, BUFFERS)` on whatever was slow. No index below was added "just in case".

## Indexes added (migration `c7e0a3f19d42`)

| Index | Query it serves | Before → after (measured) |
|---|---|---|
| `refresh_tokens (replaced_by_id)` | the `ON DELETE SET NULL` trigger of the self-referencing key — runs once per deleted token (session purge, logout-all, password reset, account erasure) | deleting 18,675 of 80,000 expired tokens: **186.6 s → 1.2 s** (the trigger seq-scanned the table for every row) |
| `articles (excerpt) gin_trgm_ops` | news search ORs title / excerpt / tag matches; the excerpt branch had no index, forcing a walk of every published article | selective query on 3,000 articles: **28 ms → 1.8 ms**; the old plan read every article and filtered (cost grows linearly with the archive); the search query was also rewritten as three index-backed candidate queries merged with `UNION` |
| `favourite_teams (created_at)` | "which teams gained followers today" (trending) filters a 24 h window | 60,000 rows: **≈ 22 ms (seq scan) → ≈ 1.5 ms (bitmap index scan)** |
| `lower(users.email)` | login, registration, reset and the CLI now match case-insensitively (`WHERE lower(email) = …`) | 20,000 users: **≈ 250 ms (seq scan) → < 1 ms warm (index scan)**; without it every sign-in would scan the `users` table |

## Foreign keys without a supporting index (full audit)

A query over `pg_constraint` found 16 single-column foreign keys whose referencing column is not the leading column of any index. Only
the first mattered and was fixed (above). The rest were reviewed and left alone because the parent rows are never deleted in
normal operation and the referencing tables are tiny: `comments.moderated_by` (largest table; one scan if a *moderator* is ever deleted — revisit if
staff accounts start being purged), `articles.featured_media_id`, `match_events.assist_player_id`, `match_lineups.team_id`, `polls.created_by`,
`player_season_statistics.team_id`, `article_categories.competition_id`, `article_gallery.media_id`, and six report/revision/folder `*_by` columns on empty tables.
Re-run: the query is in `docs/operations/database.md#audit-query` below.

## Query analysis results

Top statements by total time during the HTTP load (`pg_stat_statements`): everything was under 6 ms mean **except** the article search (96 ms, fixed) and the trending
follow count (112 ms, fixed). Per-request SQL is bounded and constant, enforced by `tests/test_query_budgets.py`:

| Endpoint (cold cache) | SQL statements |
|---|---|
| `/matches/today`, `/matches/live` | 4 |
| `/matches/{id}` | 8 |
| `/matches/{id}/lineups` | 6 |
| `/matches/{id}/statistics` | 2 |
| `/competitions` | 1 (was a provider call) |
| `/competitions/{id}/standings` | 4 |
| `/teams/{id}`, `/teams/{id}/fixtures` | 2, 5 |
| `/search` | 8 |

**N+1:** the test measures statement counts with 3 vs 40 comments, 1 vs 13 articles, 3 vs 25 followers; none of the hot paths grows with the data. The one real N+1 found
was the notification fan-out (4 statements per recipient): a goal for a team with 9,076 recipients issued **36,315 statements and took 130 s**; after batching it issues 16 and
takes **0.65 s** for the delivery step (resolving who to notify is unchanged: ≈ 5 s for 9,076 recipients, dominated by inserting their de-duplication rows). It also failed outright above ~8,000 recipients (bind-parameter limit) — see `findings.md` S-4.

## Connection pool and timeouts

| Setting | Value | Why |
|---|---|---|
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 10 / 10 | **per process**. With `WEB_CONCURRENCY=4` and a Celery worker of concurrency 2 the stack can hold up to ≈ 120 connections: raise Postgres' `max_connections` (default 100) or lower the pools. Measured at 100–400 virtual users on one worker: 11–21 connections used, 1–2 active |
| `DB_POOL_TIMEOUT_SECONDS` | 10 | when every connection is busy a request waits at most 10 s, then gets **503 + Retry-After** (`db_pool_exhausted_total`, alert) rather than queueing forever |
| `DB_POOL_RECYCLE_SECONDS` / `pool_pre_ping` | 1800 / on | a connection older than 30 min, or one a restart/firewall killed, is replaced before use (verified: the API recovers on its own ≈ 5 s after Postgres is restarted) |
| `DB_STATEMENT_TIMEOUT_MS` | 15000 | a runaway query is cancelled by the server (tested); also why the purge job deletes in batches |
| asyncpg connect / command timeout | 5 s / 30 s | the driver default was 60 s *per connection attempt* — a black-holed database would have hung every request |
| `application_name` | the service name | `pg_stat_activity` shows which process owns each connection |

Production should use `pg_stat_statements` (`shared_preload_libraries='pg_stat_statements'`) and log slow statements
(`log_min_duration_statement=250`); both are what this review used.

## Maintenance

* **Autovacuum** is on (Postgres defaults). The tables that churn are `notification_log`, `engagement_buckets`, `refresh_tokens`, `payment_events`; run `ANALYZE` after any bulk load or backfill.
* **Growth to watch** (rows/year at 100 k users, rough): `notification_log` and `comments` are the large ones; neither is purged automatically. Decide a retention for `notification_log` (it only needs to cover the dedup window — e.g. 90 days) before it passes ~50 M rows.
* **Backups, restore, migrations**: `docs/disaster-recovery/backup-restore.md`, `docs/deployment/migrations.md`.

### Audit query
```sql
SELECT c.conrelid::regclass AS tbl, a.attname AS fk_column, c.confrelid::regclass AS references,
       (SELECT reltuples::bigint FROM pg_class WHERE oid = c.conrelid) AS approx_rows
FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f' AND array_length(c.conkey,1) = 1
  AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1] AND i.indisvalid)
ORDER BY approx_rows DESC;
```
