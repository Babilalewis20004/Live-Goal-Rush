"""Phase 6 background jobs: scheduled publishing, poll closing, and the
community/editorial notifications. Thin Celery wrappers -- the logic lives in
`ArticleService.run_schedule`, `PollService.close_due` and
`social_notification_service`, where it is tested against the test database."""

from __future__ import annotations

import logging

from app.core.redis_client import get_redis_service
from app.db.session import AsyncSessionLocal
from app.services import social_notification_service as social
from app.services.article_service import ArticleService
from app.services.community_service import PollService
from app.worker.async_runner import run
from app.worker.celery_app import celery_app
from app.worker.failure import retry_or_raise
from app.worker.discovery_tasks import dispatch_article_notifications

logger = logging.getLogger(__name__)


def _enqueue(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:
        logger.warning("Could not enqueue %s%s", getattr(task, "name", task), args, exc_info=True)


@celery_app.task(name="app.worker.social_tasks.publish_scheduled_articles")
def publish_scheduled_articles() -> None:
    """Every minute: publish due SCHEDULED articles, archive expired ones."""

    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            published, _archived = await ArticleService(db, get_redis_service()).run_schedule()
        for article_id in published:
            _enqueue(dispatch_article_notifications, article_id)
            _enqueue(notify_editorial, article_id, "published")

    run(_go())


@celery_app.task(name="app.worker.social_tasks.close_due_polls")
def close_due_polls() -> None:
    """Every minute: close polls whose `closes_at` has passed and announce results."""

    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            closed = await PollService(db, get_redis_service()).close_due()
        for poll_id in closed:
            _enqueue(notify_poll_results, poll_id)

    run(_go())


@celery_app.task(name="app.worker.social_tasks.notify_comment_reply", bind=True, max_retries=3)
def notify_comment_reply(self, comment_id: int) -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await social.notify_comment_reply(db, comment_id)

    try:
        run(_go())
    except Exception as exc:
        retry_or_raise(self, exc)


@celery_app.task(name="app.worker.social_tasks.notify_editorial", bind=True, max_retries=3)
def notify_editorial(self, article_id: int, event: str) -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await social.notify_editorial(db, article_id, event)

    try:
        run(_go())
    except Exception as exc:
        retry_or_raise(self, exc)


@celery_app.task(name="app.worker.social_tasks.notify_poll_results", bind=True, max_retries=3)
def notify_poll_results(self, poll_id: int) -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await social.notify_poll_results(db, poll_id)

    try:
        run(_go())
    except Exception as exc:
        retry_or_raise(self, exc)
