# API outage or error spike

**Symptoms.** Users see errors or spinners; `ApiErrorBudgetBurn`, `DatabaseConnectionPoolExhausted` or `ApiDown` firing;
nginx returns 502/504; `/health/ready` is 503 or unreachable.

**Impact.** Web and mobile cannot load data. Cached pages may still be served by a CDN if you run one. Mobile shows its last
saved copy with an "offline / last updated" banner — it does not show stale scores as current.

## Diagnose

1. Is the process alive? `curl -s localhost/health/live` (through nginx) and `docker compose … exec api python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health/live').read())"`.
   *Alive but not ready* means a dependency is down → [database-outage.md](database-outage.md) / [redis-outage.md](redis-outage.md).
2. `$C ps` — is `api` restarting? `$C logs --tail 200 api | grep -E '"level":"(ERROR|CRITICAL)"'`. A crash loop on start usually prints
   `Refusing to start with ENVIRONMENT=production: unsafe configuration` — a mis-set variable (the message lists them all).
3. Pool exhaustion: `/api/v1/admin/system` → `db_pool.checked_out` at `size + overflow` and 503 responses with `Retry-After`.
   Either traffic outgrew the workers or a slow query holds connections: `docker compose … exec postgres psql -U football -c "select pid, now()-query_start as running, left(query,100) from pg_stat_activity where state='active' order by 2 desc limit 10"`.
4. CPU saturation (the measured limiting factor, `docs/operations/capacity.md`): `docker stats --no-stream`. `api` pinned at ~1 core per worker with Postgres idle = add workers.

## Fix

| Cause | Action |
|---|---|
| Traffic > capacity (CPU-bound, DB idle) | raise `WEB_CONCURRENCY` (one uvicorn worker per core) and/or run another API container behind nginx; `$C up -d --no-deps --scale api=2 api` then add it to the nginx upstream |
| Pool exhausted by one slow query | cancel it (`select pg_cancel_backend(pid)`), then find the cause in `pg_stat_statements`; the server-side `statement_timeout` (15 s) normally limits the damage |
| Bad release | `./deploy/rollback.sh` ([rollback.md](rollback.md)) |
| Unsafe/invalid configuration | fix the variables named in the log, `$C up -d api` |
| A dependency is down | its runbook |

## Verify

`python apps/api/scripts/smoke.py --base https://<site> --web https://<site> --edge`. Error rate back under 1 % for 10 minutes
(`ApiErrorBudgetBurn` resolves).

## Afterwards

Record the cause and the `request_id` of an affected request. If the fix was "more workers", update the capacity notes.
