# Observability (Phase 6a, extended in 6b)

## Structured logs

`LOG_FORMAT=json` (default) emits one JSON object per line:
`{"ts", "level", "service", "event", "logger", "request_id", …fields}`. `event` is a stable machine-readable name
(`http_request`, `comment_create`, `article_publish`, `payment_…`, `user_suspended` …); `log_event(logger, "name",
**ids)` adds fields. Fields whose names contain `password`, `token`, `secret`, `authorization`, `cookie` or `email`
are replaced with `[redacted]`; code logs ids, not bodies or personal data. A per-request `request_id` (also
returned in `X-Request-ID`) ties API and service lines together. `LOG_FORMAT=text` gives human-readable output.

## Metrics

* The API exposes `GET /metrics` (Prometheus text). It merges (a) an API-local registry — `http_requests_total{method,route,status}`
  and `http_request_duration_seconds{route}` using **route templates** (`/api/v1/teams/{team_id}/analytics`, unmatched
  → `unmatched`) so label cardinality is bounded — with (b) the Redis-aggregated counters pushed by each process
  (API, worker, scheduler) under a `role` label.
* Celery: `celery_tasks_total`, `celery_task_failures_total`, `celery_queue_length{queue}` (sampled from Redis).
* Application counters (Phase 6a): media, publishing, comments, reports, reactions, poll votes, notifications,
  provider/cache/WebSocket counters.
* Phase 6b: `analytics_generation_total`, `analytics_generation_failures_total`, `prediction_generation_total`,
  `prediction_evaluation_total`, `insight_generation_total`, `subscription_created_total`, `…_renewed_total`,
  `…_cancelled_total`, `…_payment_failed_total`, `payment_webhooks_total`, `…_rejected_total`,
  `premium_feature_usage_total`, `premium_feature_denied_total`.
  (Existing 6a names `comments_created_total`, `comments_reported_total`, `poll_votes_total` were kept rather than
  renamed to the singular forms in the brief, so existing dashboards keep working.)

## Prometheus and Grafana

`docker compose up` starts Prometheus (scrapes `api` and `redis_exporter`) and Grafana with the data source and
five dashboards provisioned from `monitoring/`:

| Dashboard | Shows |
|---|---|
| API & Search | request rate by status, 5xx, latency p50/p95/p99, search volume |
| Workers & Notifications | task rate/failures, queue length, notifications sent/failed/deduplicated |
| Realtime & Redis | WebSocket connections/messages, cache hit rate, Redis memory/clients |
| Community & Media | comments, reports, reactions, votes, uploads and rejection ratio |
| Analytics, Predictions & Premium | analytics/prediction/insight jobs, subscriptions, failed payments, webhooks, premium use vs paywall hits |

`monitoring/prometheus/alerts.yml` ships starting alerts (API down, 5xx rate, slow p95, queue backlog, task
failures, notification failures, Redis down, webhook rejections, payment failures, analytics generation failing).
Prometheus evaluates them; routing them to a pager (Alertmanager) is a deployment decision and is not included.

Ports: Prometheus `9090`, Grafana `3001` (default login `admin`/`admin` — change `GRAFANA_ADMIN_PASSWORD` outside
local development), MinIO `9000`/`9001`.

## Not included

Distributed tracing, log shipping, per-user product analytics, and per-job *duration* histograms for the new
Celery tasks (queue latency is visible via `celery_queue_length`; request durations are histograms).
