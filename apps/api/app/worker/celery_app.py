"""The Celery application (Phase 2 §6).

Two OS processes run against this one app object:
  `celery -A app.worker.celery_app worker` -- executes tasks.
  `celery -A app.worker.celery_app beat`   -- enqueues tasks on a schedule.

Both are just `apps/api`'s existing image with a different container
command (see docker-compose.yml's `worker`/`scheduler` services) -- no
separate codebase or dependency set.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery("football_livescore", broker=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue="football",
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# Imported for their side effects: `tasks`/`notification_tasks` each
# register their @celery_app.task functions, `schedule` sets
# celery_app.conf.beat_schedule. All need to happen whenever this module
# is imported (by either the worker or beat process).
from app.worker import notification_tasks, schedule, tasks  # noqa: E402,F401
