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
from celery.signals import (
    beat_init,
    before_task_publish,
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
)

from app.core.config import settings
from app.core.production_checks import enforce as enforce_configuration

enforce_configuration(settings)  # the worker and scheduler refuse an unsafe deployed configuration too

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
    # -- reliability (Phase 7) -------------------------------------------------------------------
    # A hung provider call or lock must not hold a worker slot forever: warn at the soft limit (the task
    # gets SoftTimeLimitExceeded and can clean up), kill at the hard one.
    task_soft_time_limit=settings.celery_task_soft_time_limit_seconds,
    task_time_limit=settings.celery_task_time_limit_seconds,
    # Redelivery after a worker dies mid-task. Safe because every task here is idempotent (upserts,
    # claim-by-unique-row); the cost of a lost sync is larger than the cost of a repeated one.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Redis re-queues an unacknowledged task after `visibility_timeout`; it must exceed the longest task.
    broker_transport_options={
        # A task whose worker is killed outright (OOM, host loss) is redelivered after this long: just over the hard limit.
        "visibility_timeout": settings.celery_task_time_limit_seconds + 60,
        "socket_connect_timeout": 5,  # publishing a task while Redis is down must fail in seconds, not hang a request
        "retry_on_timeout": True,
    },
    broker_connection_timeout=5,
    broker_connection_max_retries=None,  # keep reconnecting if Redis restarts, instead of exiting
    broker_pool_limit=10,
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
    from app.core.logging_config import configure_logging

    configure_logging("worker")
    _enable_metrics("worker")


@task_postrun.connect
def _on_task_postrun(**_kwargs) -> None:
    from app.services.metrics import metrics

    metrics.celery_task()


_task_started: dict[str, float] = {}


@before_task_publish.connect
def _propagate_request_id(headers=None, **_kwargs) -> None:
    """Carry the originating HTTP request's id into the task, so one id traces proxy -> API -> worker."""
    from app.core.logging_config import request_id_var

    request_id = request_id_var.get()
    if request_id and headers is not None:
        headers["request_id"] = request_id


@task_prerun.connect
def _on_task_prerun(task_id=None, task=None, **_kwargs) -> None:
    import time

    from app.core.logging_config import request_id_var

    if task_id:
        _task_started[task_id] = time.perf_counter()
    inherited = getattr(getattr(task, "request", None), "request_id", None) or (task.request.get("request_id") if task else None)
    request_id_var.set(inherited or (task_id[:16] if task_id else None))


@task_postrun.connect
def _log_task_finished(task_id=None, task=None, state=None, **_kwargs) -> None:
    import logging
    import time

    from app.core.logging_config import log_event, request_id_var

    started = _task_started.pop(task_id, None) if task_id else None
    if state != "RETRY":
        log_event(
            logging.getLogger("celery.task"),
            "task_finished",
            task=getattr(task, "name", None),
            state=state,
            duration_ms=round((time.perf_counter() - started) * 1000, 1) if started is not None else None,
        )
    request_id_var.set(None)


@task_failure.connect
def _on_task_failure(task_id=None, exception=None, sender=None, args=None, kwargs=None, **_kwargs) -> None:
    import logging

    from app.core.logging_config import log_event
    from app.services.metrics import metrics
    from app.worker.failure import classify, on_task_failure

    metrics.celery_task(failed=True)
    log_event(
        logging.getLogger("celery.task"),
        "task_failed",
        level=logging.ERROR,
        task=getattr(sender, "name", None),
        task_id=task_id,
        error=type(exception).__name__,
        classification=classify(exception),
    )
    on_task_failure(sender, task_id, exception, args or (), kwargs or {})


@beat_init.connect
def _on_beat_init(**_kwargs) -> None:
    from app.core.logging_config import configure_logging

    configure_logging("scheduler")
    _enable_metrics("scheduler")


# Imported for their side effects: `tasks`/`notification_tasks`/`discovery_tasks` each
# register their @celery_app.task functions, `schedule` sets
# celery_app.conf.beat_schedule. All need to happen whenever this module
# is imported (by either the worker or beat process).
from app.worker import analytics_tasks, discovery_tasks, notification_tasks, ops_tasks, schedule, social_tasks, tasks  # noqa: E402,F401
