# PostgreSQL outage

**Symptoms.** `DatabaseUnreachable`; `/health/ready` → 503 with `"database":"unavailable"`; API returns **503 + `Retry-After`** for
anything not served from Redis; Celery tasks fail with connection errors (and are retried with backoff, then recorded in `failed_jobs`).

**Impact.** Reads that are cached in Redis keep working until their TTL (30 s – 15 min). Everything else is a retryable 503.
The process stays *alive* (liveness does not depend on the database), so containers are not restarted into a worse state.
Recovery needs **no restart**: pooled connections are validated before use (`pool_pre_ping`) and recycled every 30 minutes —
verified by restarting Postgres under a running stack (`docs/operations/failure-modes.md`: API healthy again about 6 s after the database came back).

## Diagnose

1. `$C ps postgres` and `$C logs --tail 100 postgres`.
2. Out of connections? `psql -c "select count(*), state from pg_stat_activity group by state"` against `max_connections`
   (`show max_connections`). Connections used ≈ (pool + overflow) × (API workers + Celery processes).
3. Disk full / corruption: `df -h`, the Postgres log for `PANIC` or `could not write`.

## Fix

| Cause | Action |
|---|---|
| Container stopped/crashed | `$C up -d postgres` — it recovers from its WAL automatically; watch `$C logs -f postgres` for "database system is ready" |
| Too many connections | lower `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` or `WEB_CONCURRENCY`, or raise `max_connections`; kill idle-in-transaction sessions: `select pg_terminate_backend(pid) from pg_stat_activity where state='idle in transaction' and now()-state_change > interval '5 minutes'` |
| Disk full | free space (old backups in `./backups`, Docker images `docker system prune`), then restart |
| Data corruption / lost volume | [backup-restoration.md](backup-restoration.md) — measured: 304 MB restores in about 80 s |
| Host failure | provision a host, restore the latest backup, point the stack at it |

## Verify

`/health/ready` → 200; `GET /api/v1/admin/system` → `database: ok`; failed jobs from the outage appear in
`GET /api/v1/admin/failed-jobs` — re-trigger what matters (the periodic syncs recover on their own).

## Afterwards

Check `PaymentEvent`s received during the outage: the processor retries failed webhooks, and processing is idempotent, so
no action is needed beyond confirming `payment_webhooks_failed_total` stopped growing.
