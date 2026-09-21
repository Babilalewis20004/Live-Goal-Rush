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
}
