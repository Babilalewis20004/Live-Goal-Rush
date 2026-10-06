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
from celery.signals import beat_init, worker_process_init

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


def _enable_metrics(role: str) -> None:
    """Push this process's counters to Redis so the API's /metrics can show
    provider/sync activity (Phase 5). Best-effort: metrics must never stop a
    worker from starting."""
    import logging
    import os

    try:
        from app.core.redis_client import get_sync_redis_service
        from app.services.metrics import metrics

        metrics.enable_aggregation(os.environ.get("METRICS_ROLE", role), get_sync_redis_service().raw)
    except Exception:
        logging.getLogger(__name__).warning("Cross-process metrics unavailable", exc_info=True)


@worker_process_init.connect
def _on_worker_process_init(**_kwargs) -> None:
    _enable_metrics("worker")


@beat_init.connect
def _on_beat_init(**_kwargs) -> None:
    _enable_metrics("scheduler")


# Imported for their side effects: `tasks`/`notification_tasks` each
# register their @celery_app.task functions, `schedule` sets
# celery_app.conf.beat_schedule. All need to happen whenever this module
# is imported (by either the worker or beat process).
from app.worker import notification_tasks, schedule, tasks  # noqa: E402,F401
