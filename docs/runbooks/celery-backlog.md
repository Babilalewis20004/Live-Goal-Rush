# Celery backlog, silent worker, or failing jobs

**Symptoms.** `CeleryBacklog` (queue > 200 for 10 min), `CeleryWorkerSilent` (queued tasks, none finishing),
`FailedJobsNeedAttention` (> 20 unresolved), notifications late, scores stale.

## Diagnose

```bash
$C ps worker scheduler                       # worker should be (healthy); beat has no healthcheck by design
$C logs --tail 100 worker                    # task_finished / task_failed lines: task, duration_ms, classification, request_id
curl -s localhost/api/v1/admin/system -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.queue_length,.unresolved_failed_jobs'
docker compose … exec redis redis-cli -a "$REDIS_PASSWORD" llen football     # queue depth
```

* **Worker down or wedged** → `$C restart worker`. Tasks are acknowledged *after* they finish (`task_acks_late`) and are
  idempotent, so a task killed mid-run is simply re-delivered. A task running past 540 s receives `SoftTimeLimitExceeded`
  and is killed at 600 s — a stuck provider call cannot hold a slot forever.
* **Slow task** → the `task_finished` log line has `duration_ms`; the periodic jobs normally take 0.01–2 s on a 440 k-comment database
  (`docs/operations/load-testing.md`). A long one is almost always the provider (see [provider-outage.md](provider-outage.md)).
* **Queue growing because work is produced faster than consumed** → add worker capacity: `$C up -d --scale worker=2 worker` or
  `CELERY_CONCURRENCY=4`.
* **No avalanche after an outage:** every beat entry carries an `expires` equal to its interval, so ticks that piled up
  while the worker was away are dropped instead of all firing at once on recovery.

## Failed jobs (the dead-letter table)

Anything that exhausted its retries — or was never retryable — is in `failed_jobs`:

```
GET  /api/v1/admin/failed-jobs?resolved=false[&task=app.worker.tasks.sync_team]
POST /api/v1/admin/failed-jobs/{id}/resolve   {"note": "provider recovered"}      # audit-logged
```

Each row shows the task, error type, **classification** (`temporary` / `database` were retried with exponential backoff;
`validation` / `authentication` / `permanent` were deliberately *not* retried), retry count, how many times it recurred
(`occurrences` — repeats fold into one row), the entity (`team:42`), and the `request_id` to trace the originating request.
Error text is scrubbed of API keys and tokens before storage.

| Classification | Meaning | Typical action |
|---|---|---|
| `temporary` | provider/network blip, retries exhausted | usually resolves itself on the next scheduled run; resolve the row |
| `database` | Postgres unreachable | see [database-outage.md](database-outage.md) |
| `authentication` | provider rejected the key | rotate/fix the key |
| `validation` | malformed payload (a provider schema change?) | read the error, fix the mapping, deploy |
| `permanent` | a bug | fix and deploy; re-run the task by hand: `$C exec api python -c "from app.worker.tasks import sync_team; sync_team.delay(42)"` |

## Verify

Queue near zero, `failed_jobs_unresolved` falling, `celery_task_failures_total` flat.
