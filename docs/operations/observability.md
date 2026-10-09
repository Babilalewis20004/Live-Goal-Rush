# Observability: health, metrics, logs, tracing, alerts

Builds on the Phase 6 stack (Prometheus + Grafana + JSON logs, `docs/architecture/observability.md`). Phase 7 adds the probes,
state gauges, request correlation across processes, and production alerts.

## Health endpoints

| Endpoint | Meaning | Depends on | Used by |
|---|---|---|---|
| `GET /health/live` | the process is running and able to answer | **nothing** | container `HEALTHCHECK`, orchestrator liveness — a database blip must never get containers restarted |
| `GET /health/ready` | this instance can serve traffic | PostgreSQL **and** Redis (2 s timeout each, in parallel). The football provider is *reported* but not required: stored data is still served | load balancer / deploy gating (`--wait`), smoke test |
| `GET /health` | full human-readable report (all three) | database, Redis, provider config | humans, the dev compose healthcheck |
| `GET /version` | `{version, git_sha, environment}` | nothing | deploy verification, support |

Worker: Celery `inspect ping` healthcheck in compose. Beat has no probe by design; its liveness is "the queue is being fed" (the `CeleryWorkerSilent` rule and `football_live_data_age_seconds`).

## Metrics (`/metrics`, Prometheus text; not routed by nginx)

Existing: HTTP request count/latency by route *template*, search latency, Celery tasks/failures/queue length, cache hits/misses, WebSocket connections/messages,
provider requests/errors/429s, notifications, media, community, billing/webhooks, analytics. **Added in Phase 7:**

| Metric | What it answers |
|---|---|
| `app_build_info{version,git_sha,environment}` | what is running |
| `app_dependency_up{dependency=database\|redis\|provider_configured}` | can the API reach what it needs (checked per scrape) |
| `db_pool_connections{state=size\|checked_out\|overflow}` | pool saturation per process |
| `db_pool_exhausted_total`, `db_unavailable_total` | requests refused with 503 because of the database |
| `failed_jobs_unresolved` | dead-letter size |
| `football_live_data_age_seconds` | age of the stalest live match's last provider sync (0 when nothing is live) — **the stale-data alert** |
| `websocket_connections_process`, `websocket_clients_evicted_total` | socket load and clients dropped for not reading |
| `payment_webhooks_failed_total`, `payment_webhooks_stale_total` | webhook processing health; out-of-order events ignored |
| `rate_limited_total`, `login_failures_total`, `account_deletions_total` | abuse / privacy signals |

The coverage table the Phase 7 brief asks for: **API** (requests, errors, latency) ✓ · **Database** (pool state, outages, slow queries via `pg_stat_statements`/`log_min_duration_statement`) ✓ ·
**Redis** (`redis_exporter`: memory, hit rate, clients; `app_dependency_up`) ✓ · **Celery** (queue depth, failures, task duration in the `task_finished` log line, dead letters) ✓ ·
**WebSockets** (connections, evictions) ✓ · **Football provider** (requests, errors, 429s, data age) ✓ · **Payments** (webhooks received / rejected / failed / stale, payment failures) ✓.
Not collected: container CPU/memory (add cAdvisor or your platform's agent), Postgres server internals (add `postgres_exporter`), backup success (a node-exporter textfile metric — see below).

## Structured logs

One JSON object per line on stdout for every process (API, worker, scheduler):

```json
{"ts":"2026-10-08T22:14:09.311Z","level":"INFO","service":"api","event":"http_request","request_id":"3f9c1ed4e5c6408e",
 "method":"GET","route":"/api/v1/matches/{match_id}","status":200,"duration_ms":14.2,"user_id":1}
{"ts":"…","service":"worker","event":"task_finished","request_id":"3f9c1ed4e5c6408e","task":"app.worker.tasks.sync_team","state":"SUCCESS","duration_ms":812.4}
{"ts":"…","service":"worker","event":"task_failed","task":"…","error":"HTTPStatusError","classification":"temporary"}
```

Fields: `ts` (UTC, ms), `service`, `level`, `event` (a stable name to filter on), `request_id`, `user_id` where authenticated, `duration_ms`, `error`/`exception`.
**Never logged:** passwords, tokens (access, refresh, reset), cookies, `Authorization`, API keys, payment credentials, email addresses — fields whose *name* contains
`password|token|secret|authorization|cookie|email` are replaced by `[redacted]`, errors recorded in the dead-letter table are scrubbed of URLs' query strings and credentials, and
the reset token is no longer logged at all. Health and metrics requests are not logged per request.

## Request correlation

```
client ──► nginx ──► API ──► Celery task ──► (database / provider calls logged with the same id)
          $request_id  X-Request-ID       headers["request_id"]        task logs carry request_id
```

nginx generates `$request_id` for every request and passes it as `X-Request-ID`; the JSON access log records it. The API accepts a well-formed incoming id
(`[A-Za-z0-9._-]{8,64}` — anything else is replaced, so a hostile header cannot inject into logs), puts it in every log line, returns it as `X-Request-ID`, and
attaches it to every Celery task it publishes; the worker restores it for the duration of the task and stores it on a dead-letter row. Search all three log streams for one id to reconstruct a request.
Database-level correlation is by `application_name` (the service) and timestamps — SQL comments carrying the id were not added (they defeat `pg_stat_statements` grouping).

## Alerts (`monitoring/prometheus/alerts.yml`, 24 rules, validated with `promtool`)

Thresholds are deliberately conservative: every rule has a `for:` of 1–30 minutes so a blip pages nobody. Wire Prometheus to Alertmanager (or your platform's alerting) —
the rules are included, the paging integration is a deployment decision.

| Alert | Fires when | Severity |
|---|---|---|
| `ApiDown` | `/metrics` unreachable 1 min | critical |
| `ApiErrorBudgetBurn` | > 2 % of requests are 5xx for 5 min (the older `HighServerErrorRate` is 5 %) | critical |
| `ApiLatencyP99High` | p99 > 3 s for 10 min (and `SlowRequests`: p95 > 1 s) | warning |
| `DatabaseUnreachable` | API cannot reach Postgres 1 min | critical |
| `DatabaseConnectionPoolExhausted` | any request refused for lack of a connection, 2 min | critical |
| `RedisUnreachableFromApi` / `RedisDown` | API / exporter cannot reach Redis 1 min | critical |
| `CeleryBacklog` | queue > 200 for 10 min | warning |
| `CeleryWorkerSilent` | tasks queued but none finishing, 10 min | critical |
| `CeleryTaskFailures`, `FailedJobsNeedAttention` | failure rate > 0.1/s; > 20 unresolved dead letters 30 min | warning |
| `FootballLiveDataStale` | a live match not synced for > 5 min, 3 min | critical |
| `FootballProviderFailing` | > 50 % provider requests failing 15 min | warning |
| `WebSocketClientsBeingEvicted` | > 1 eviction/s for 10 min | warning |
| `PaymentWebhookProcessingFailing` | any verified webhook failed to process in 15 min | critical |
| `WebhookSignatureRejections`, `PaymentFailures` | signature rejections / failed renewals (Phase 6b) | warning |
| `LoginFailureSpike` | > 5 failed sign-ins/s for 10 min | warning |
| `BackupStale` / `BackupMetricMissing` | no successful backup in 26 h / backup reporting not wired | critical / warning |

**Backup monitoring.** `deploy/backup/backup.sh` writes `backup_last_success_timestamp_seconds` to `BACKUP_METRICS_FILE` (a node-exporter textfile-collector file) and/or pings
`BACKUP_HEARTBEAT_URL` (healthchecks.io-style: it alerts when the ping *stops*, which catches a cron job that never ran — something no metric can).

**Dashboards.** Five Grafana dashboards from Phase 6 (`monitoring/grafana/dashboards/`): API & search, realtime & Redis, workers & notifications, community & media, analytics & billing.
Add panels for the Phase 7 gauges above; the data is already scraped.
