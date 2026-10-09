"""Notification dispatch Celery task (Phase 3 §12/§20).

Triggered from `worker/tasks.py::_publish_changes` as an independent task
enqueued right after the existing Redis Pub/Sub publish -- a second,
decoupled consumer of the same `RealtimeEvent` stream that already powers
the WebSocket layer (never the WebSocket layer itself; spec §27). Runs on
its own retry schedule, separate from football-provider sync retries, so a
slow/failing push provider can never slow down or crash the live sync
loop.
"""

from __future__ import annotations

import logging

from app.db.session import AsyncSessionLocal
from app.events.schemas import RealtimeEvent
from app.services.notification_dispatch_service import resolve_targets
from app.services.notifications.service import NotificationService
from app.worker.async_runner import run
from app.worker.celery_app import celery_app
from app.worker.failure import retry_or_raise

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.notification_tasks.dispatch_notifications", bind=True, max_retries=3)
def dispatch_notifications(self, event_payload: dict) -> None:
    async def _run_task() -> None:
        event = RealtimeEvent.model_validate(event_payload)
        async with AsyncSessionLocal() as db:
            targets = await resolve_targets(db, event)
            if not targets:
                return

            logger.info(
                "Dispatching %d notification(s) for match=%s type=%s",
                len(targets),
                event.match_id,
                event.type.value,
            )
            await NotificationService(db).send_to_users(targets)

    try:
        run(_run_task())
    except Exception as exc:
        logger.exception("dispatch_notifications failed for payload=%s", event_payload)
        retry_or_raise(self, exc)
