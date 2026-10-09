"""Celery beat schedule (Phase 2 §9).

All intervals come from `Settings` -- nothing here is hard-coded -- so
`docker-compose.yml`/`.env` control polling frequency without a code
change. `sync_live_matches` runs most often (it's the adaptive-polling
core); fixtures/competitions run on coarser, fixed intervals since they
change far less often than an in-progress match's score.
"""

from __future__ import annotations

from app.core.config import settings
from app.worker.celery_app import celery_app

_FIXTURES_INTERVAL_SECONDS = max(settings.upcoming_poll_interval_seconds * 5, 300)
_COMPETITIONS_INTERVAL_SECONDS = max(settings.upcoming_poll_interval_seconds * 10, 600)

celery_app.conf.beat_schedule = {
    "sync-live-matches": {
        "task": "app.worker.tasks.sync_live_matches",
        "schedule": settings.live_poll_interval_seconds,
    },
    "sync-upcoming-kickoffs": {
        "task": "app.worker.tasks.sync_upcoming_kickoffs",
        "schedule": settings.upcoming_poll_interval_seconds,
    },
    "sync-post-match": {
        "task": "app.worker.tasks.sync_post_match",
        "schedule": settings.post_match_sync_interval_seconds,
    },
    "sync-fixtures": {
        "task": "app.worker.tasks.sync_fixtures",
        "schedule": _FIXTURES_INTERVAL_SECONDS,
    },
    "sync-competitions": {
        "task": "app.worker.tasks.sync_competitions",
        "schedule": _COMPETITIONS_INTERVAL_SECONDS,
    },
    # Discovery: fold Redis view counters into Postgres often (cheap), and
    # refresh the trending lists on a coarser cycle.
    "aggregate-engagement": {
        "task": "app.worker.discovery_tasks.aggregate_engagement",
        "schedule": 60,
    },
    "calculate-trending": {
        "task": "app.worker.discovery_tasks.calculate_trending",
        "schedule": 300,
    },
    # Phase 6: scheduled publishing and poll closing, both idempotent.
    "publish-scheduled-articles": {
        "task": "app.worker.social_tasks.publish_scheduled_articles",
        "schedule": 60,
    },
    "close-due-polls": {
        "task": "app.worker.social_tasks.close_due_polls",
        "schedule": 60,
    },
    # Phase 6b: predictions, evaluation, insights, analytics warm-up, matchday notices,
    # subscription housekeeping. All idempotent.
    "generate-predictions": {"task": "app.worker.analytics_tasks.generate_predictions", "schedule": 1800},
    "evaluate-predictions": {"task": "app.worker.analytics_tasks.evaluate_predictions", "schedule": 900},
    "generate-insights": {"task": "app.worker.analytics_tasks.generate_insights", "schedule": 600},
    "calculate-team-analytics": {"task": "app.worker.analytics_tasks.calculate_team_analytics", "schedule": 900},
    "notify-matchday": {"task": "app.worker.analytics_tasks.notify_matchday", "schedule": 900},
    "process-subscription-events": {"task": "app.worker.analytics_tasks.process_subscription_events", "schedule": 3600},
}

# Phase 7: housekeeping. Resolved failed jobs are kept 30 days, unresolved ones 90; both purged daily.
celery_app.conf.beat_schedule["purge-operational-data"] = {
    "task": "app.worker.ops_tasks.purge_operational_data",
    "schedule": 86400,
}

# A scheduled run that has not started within one interval is stale: the next tick supersedes it. Without an
# expiry, a worker outage of ten minutes queues twenty `sync_live_matches` runs that all fire at once on
# restart and burn the provider's request quota. `expires` makes the backlog evaporate instead.
for _entry in celery_app.conf.beat_schedule.values():
    _entry.setdefault("options", {})["expires"] = max(int(_entry["schedule"]), 30)
