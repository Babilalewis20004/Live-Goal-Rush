"""Discovery background jobs (discovery §37): engagement aggregation, trending
precomputation and article notifications. Same shape as the other task
modules -- thin Celery wrappers over async service code, run on the worker's
persistent event loop (`async_runner.run`).
"""

from __future__ import annotations

import logging

from app.core.redis_client import get_redis_service
from app.db.session import AsyncSessionLocal
from app.services.content_notification_service import claim_article, claim_users, resolve_article_targets
from app.services.discovery_service import refresh_trending
from app.services.engagement_service import aggregate_engagement as aggregate
from app.services.notifications.service import NotificationService
from app.worker.async_runner import run
from app.worker.celery_app import celery_app
from app.worker.failure import retry_or_raise

logger = logging.getLogger(__name__)


@celery_app.task(name="app.worker.discovery_tasks.aggregate_engagement")
def aggregate_engagement() -> None:
    """Redis hourly view/search counters -> `engagement_buckets` (+ article view counts)."""

    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            written = await aggregate(get_redis_service().raw, db)
            if written:
                logger.info("Aggregated %d engagement row(s)", written)

    run(_go())


@celery_app.task(name="app.worker.discovery_tasks.calculate_trending")
def calculate_trending() -> None:
    """Recompute and cache trending teams/players/competitions/articles."""

    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            counts = await refresh_trending(db, get_redis_service())
            logger.info("Trending refreshed: %s", counts)

    run(_go())


@celery_app.task(name="app.worker.discovery_tasks.dispatch_article_notifications", bind=True, max_retries=3)
def dispatch_article_notifications(self, article_id: int) -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            article = await claim_article(db, article_id)
            if article is None:
                return  # already notified, or no longer published
            targets = await resolve_article_targets(db, article)
            users = await claim_users(db, article.id, targets)
            if not users:
                return
            logger.info("Notifying %d user(s) about article=%s", len(users), article.id)
            service = NotificationService(db)
            payload = service.build_article_payload(article.slug, article.title, article.excerpt)
            for user_id in users:
                await service.send_payload_to_user(user_id, payload)

    try:
        run(_go())
    except Exception as exc:
        logger.exception("dispatch_article_notifications failed for article=%s", article_id)
        retry_or_raise(self, exc)
