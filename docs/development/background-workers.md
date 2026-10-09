# Background Workers (Phase 2)

Celery + Redis (broker), per the spec's suggested default — nothing in
Phase 1 already provided background jobs, so there was no existing system
to prefer instead. Two OS processes run the same codebase
(`apps/api/app/worker/celery_app.py`) with a different container command:

```bash
celery -A app.worker.celery_app worker --loglevel=info   # executes tasks
celery -A app.worker.celery_app beat --loglevel=info     # enqueues tasks on a schedule
```

In Docker Compose these are the `worker` and `scheduler` services, both
built from `apps/api`'s existing Dockerfile — not a separate codebase or
dependency set (`docker-compose.yml`).

## Why Celery, not raw `asyncio` tasks in the API process

The spec explicitly asks for separate worker/scheduler responsibilities
and says not to run long-running sync directly inside FastAPI request
handlers. A Celery worker is a genuinely separate process (or several,
`--concurrency=N`) that can be scaled, restarted, and monitored
independently of the API — an in-process `asyncio` background task would
tie the sync pipeline's lifetime and failure modes to the API server's.

## Bridging sync Celery into async application code

Celery's task execution model is synchronous, but `FootballService`, the
providers, and the DB session are all `async`. Each task runs its async
body on **one event loop that lives for the worker process's whole
lifetime** (`app/worker/async_runner.py::run` — extracted from
`worker/tasks.py` in Phase 3 so `worker/notification_tasks.py` can share
it too), not a fresh `asyncio.run()` per task. This isn't just style —
`asyncio.run()` per task is actually a bug waiting to happen:
`app/db/session.py`'s async SQLAlchemy engine (and its pooled asyncpg
connections) is a process-wide singleton, and asyncpg connections are
bound to the event loop they were opened on. A prefork worker executes
many tasks over its process lifetime; tearing down and recreating the
loop on every single one leaves the *next* task's pooled connections
attached to a dead loop
(`RuntimeError: ... got Future ... attached to a different loop`) —
encountered and fixed during this implementation. See `run`'s docstring.

## Tasks

All in `app/worker/tasks.py`; all follow the same shape: guarded provider
call(s) (`provider_guard.call_with_backoff` — see `realtime.md`) → upsert
into Postgres via `FootballService` (idempotent — see below) → change
detection + Pub/Sub publish for whatever meaningfully changed (`realtime.md`).

| Task | Beat schedule | Purpose |
| --- | --- | --- |
| `sync_live_matches` | `LIVE_POLL_INTERVAL_SECONDS` (15s) | The adaptive-polling core — see `realtime.md` |
| `sync_upcoming_kickoffs` | `UPCOMING_POLL_INTERVAL_SECONDS` (60s) | Database-driven near-kickoff checks |
| `sync_post_match` | `POST_MATCH_SYNC_INTERVAL_SECONDS` (60s) | Database-driven post-finish correction window |
| `sync_fixtures` | `max(UPCOMING_POLL_INTERVAL_SECONDS * 5, 300)`s | Today/tomorrow/7-day window/yesterday, across every fixture |
| `sync_competitions` | `max(UPCOMING_POLL_INTERVAL_SECONDS * 10, 600)`s | Competition metadata, fixtures, and standings |
| `sync_team(team_provider_id)` | not scheduled | On-demand team sync — following a team, or a team page that finds no stored squad (*Phase 4:* now also syncs the squad) |
| `sync_player(player_provider_id)` | not scheduled | *(Phase 4)* On-demand player profile sync, queued once per hour by a player page that finds only a stub |
| `sync_competition_standings(competition_id)` | queued on `MATCH_FINISHED` | *(Phase 4)* Standings + top scorers for one competition; body is `sync_competition_standings_now` so tests/E2E can drive it directly |

**Phase 4 additions inside existing tasks:** `_sync_one_match` (used by
`sync_live_matches`, `sync_upcoming_kickoffs`, `sync_post_match`) also syncs
lineups/team statistics/player statistics via `MatchCentreService` when the
provider's `capabilities` allow it, through `GuardedProvider` (every call
retried with the Phase 2 backoff); `sync_competitions` also syncs top
scorers. No new beat entries were needed — see `match-centre.md` §4.

Schedule assembled in `app/worker/schedule.py`, entirely from `Settings` —
no interval is hard-coded in task code.

**Phase 3 addition:** `app/worker/notification_tasks.py::dispatch_notifications`
is not beat-scheduled either — it's enqueued once per `RealtimeEvent`,
directly from `worker/tasks.py::_publish_changes`, right after the
existing Redis Pub/Sub publish. It runs in the same `worker` process/queue
as everything else here (no new Celery queue or service), but as its own
task with its own retry policy (`bind=True, max_retries=3`), so a slow or
failing push provider can never slow down or crash the sync tasks above.
See `docs/architecture/notifications.md` for the full pipeline.

### Discovery tasks (`app/worker/discovery_tasks.py`)

| Task | Schedule | Does |
| --- | --- | --- |
| `aggregate_engagement` | every 60 s | Moves Redis hourly view/search counters into `engagement_buckets` and `articles.view_count` (atomic claim by `RENAME`; at-least-once) and purges buckets older than 30 days |
| `calculate_trending` | every 5 min | Recomputes and caches trending teams/players/competitions/articles |
| `dispatch_article_notifications(article_id)` | on first publish | Claims the article, resolves opted-in/relevant/under-cap users, claims each user, sends via the Phase 3 senders |

They follow the same shape as the sync tasks (thin wrapper over async service code on the
persistent event loop). Nothing expensive runs in an API route: the API only increments a
Redis counter, reads caches, or enqueues the notification task.

## Idempotency (spec §24)

Every sync ultimately calls `upsert_by_provider_id` /
`upsert_by_unique_fields` (`app/services/upsert.py`) — get-or-create by a
stable key, update in place if found. Running the exact same sync twice:

- Does not create a duplicate `Match` row (`provider_id` is unique).
- Does not create a duplicate `MatchEvent` row (`(match_id, provider_id)`
  is unique — see `database.md`'s "Event identity" note).
- Does not corrupt scores — a re-sync overwrites `home_score`/`away_score`
  with the provider's current values; it doesn't increment or accumulate
  anything.
- Does not duplicate a real-time notification — change detection compares
  against the *last published* state, not the last *synced* state, so
  re-syncing identical data produces zero new `RealtimeEvent`s (see
  `realtime.md`'s change-detection table).

## Provider failure handling & retry/backoff

Covered in full in `realtime.md` (`call_with_backoff`). Summary: each
provider call gets up to `SYNC_MAX_RETRIES` attempts with exponential
backoff (`SYNC_BACKOFF_SECONDS * 2^attempt`), a 429 is tracked separately
from other errors, and exhausting retries raises
`ProviderUnavailableError`, which every task catches and treats as "log
and skip this cycle" — never an unhandled exception that would crash the
worker or leave a task retrying instantly in a hot loop.

## Running locally without Docker

```bash
cd apps/api
celery -A app.worker.celery_app worker --loglevel=info --concurrency=2
celery -A app.worker.celery_app beat --loglevel=info   # separate terminal
```

Needs the same `.env` as the API (`REDIS_URL`, `DATABASE_URL`,
`FOOTBALL_DATA_PROVIDER`, ...) — see `apps/api/.env.example`. On Windows
outside Docker, Celery's prefork pool has known issues; use
`--pool=solo` (single-threaded) if you hit them — Docker Compose (Linux
containers) doesn't need this.

## Testing

`apps/api/tests/test_event_dedup.py` exercises `FootballService.sync_match`
idempotency and event dedup directly (no Celery machinery needed — the
task functions are thin wrappers around the same service calls).
`test_provider_backoff.py` exercises `call_with_backoff`'s retry/backoff
behavior with monkeypatched sleep. Full Celery task execution (task
routing, beat scheduling) isn't unit-tested — it's config, not logic — and
is covered by the manual verification in the root
`AGENTS.md`/`docker-compose.yml` flow instead.

## Phase 6 jobs (`app/worker/social_tasks.py`, `analytics_tasks.py`)

All idempotent; none is called from a request except the cheap "enqueue a notification" ones.

| Task | Beat | Does |
|---|---|---|
| `publish_scheduled_articles` | 60 s | publish due scheduled articles, archive expired ones (atomic UPDATE … RETURNING) |
| `close_due_polls` | 60 s | close due polls, enqueue result notifications |
| `generate_predictions` | 30 min | estimate scheduled matches in the next 72 h; enqueue "estimate available" for new ones |
| `evaluate_predictions` | 15 min | score finished matches' stored predictions once |
| `generate_insights` | 10 min | refresh stored insights for live / upcoming / just-finished matches, their teams, players with stats |
| `calculate_team_analytics` | 15 min | warm the analytics cache for teams playing in 24 h |
| `notify_matchday` | 15 min | matchday reminders (24 h) and "poll closing soon" (60 min) for opted-in followers |
| `process_subscription_events` | 1 h | mark lapsed subscriptions `EXPIRED` |
| `notify_comment_reply`, `notify_editorial`, `notify_poll_results`, `notify_prediction_available`, `notify_subscription_event` | on demand | retried up to 3×, deduplicated by `(user, dedup_key)` |

Every task is counted in `celery_tasks_total` / `celery_task_failures_total`; the queue length is a gauge.
Verified in Docker: each analytics task was queued with `celery call` and succeeded on the worker.
