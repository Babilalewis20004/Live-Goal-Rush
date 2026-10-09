"""Phase 6b background jobs: predictions, evaluation, insights, analytics warm-up,
matchday/poll notifications, and subscription housekeeping.

Thin Celery wrappers -- the logic lives in `PredictionService`, `InsightGenerator`,
`AnalyticsService`, `personal_insights` and `BillingService`, where it is tested.
Every job is idempotent (re-running changes nothing that is already current) and
safe to retry; expensive work happens here, never inside an API request.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.redis_client import get_redis_service
from app.db.session import AsyncSessionLocal
from app.models.billing import Subscription
from app.models.enums import MatchStatus, SubscriptionStatus
from app.models.match import Match
from app.models.statistics import PlayerMatchStatistic
from app.services import personal_insights
from app.services.analytics_service import AnalyticsService
from app.services.billing.entitlements import subscription_grants_access
from app.services.cache import CacheAside
from app.services.insight_records import InsightGenerator
from app.services.metrics import metrics
from app.services.prediction_service import PredictionService
from app.worker.async_runner import run
from app.worker.celery_app import celery_app
from app.worker.failure import retry_or_raise

logger = logging.getLogger(__name__)


def _enqueue(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:
        logger.warning("Could not enqueue %s%s", getattr(task, "name", task), args, exc_info=True)


# -- core logic (also called directly by tests) ---------------------------------------------------------


async def generate_predictions_once(db, cache: CacheAside | None = None) -> list[int]:
    """Estimate every upcoming match in the horizon. Returns ids that got a *new* estimate."""
    service = PredictionService(db, cache)
    created: list[int] = []
    for match_id in await service.upcoming_match_ids():
        before = await service._stored(match_id)
        out = await service.generate(match_id)
        if out.status == "available" and before is None:
            created.append(match_id)
    return created


async def generate_insights_once(db, redis=None) -> int:
    """Refresh stored insights for matches that are live, upcoming (48h) or just finished (6h),
    their teams, and the players who have statistics in them."""
    now = datetime.now(timezone.utc)
    matches = (
        await db.execute(
            select(Match).where(
                (Match.status.in_([MatchStatus.LIVE, MatchStatus.HALFTIME]))
                | ((Match.status == MatchStatus.SCHEDULED) & (Match.kickoff_time <= now + timedelta(hours=48)))
                | ((Match.status == MatchStatus.FINISHED) & (Match.kickoff_time >= now - timedelta(hours=6)))
            )
        )
    ).scalars().all()
    gen = InsightGenerator(db, redis)
    written = 0
    team_ids: set[int] = set()
    for m in matches:
        written += await gen.generate_for_match(m.id)
        team_ids.update((m.home_team_id, m.away_team_id))
    for team_id in team_ids:
        written += await gen.generate_for_team(team_id)
    if matches:
        player_ids = set(
            (
                await db.execute(
                    select(PlayerMatchStatistic.player_id).where(PlayerMatchStatistic.match_id.in_([m.id for m in matches]))
                )
            ).scalars()
        )
        for player_id in player_ids:
            written += await gen.generate_for_player(player_id)
    return written


async def warm_team_analytics_once(db, cache: CacheAside) -> int:
    now = datetime.now(timezone.utc)
    ids = set()
    for m in (
        await db.execute(
            select(Match).where(Match.status == MatchStatus.SCHEDULED, Match.kickoff_time <= now + timedelta(hours=24))
        )
    ).scalars():
        ids.update((m.home_team_id, m.away_team_id))
    service = AnalyticsService(db, cache)
    for team_id in ids:
        await service.team_analytics(team_id, "overall", 10)
    return len(ids)


async def expire_lapsed_subscriptions_once(db) -> int:
    """Tidy statuses: a subscription whose access has run out becomes EXPIRED. Access itself is
    computed from dates on every request, so this changes nothing a user can do -- it keeps
    the data and the counts honest."""
    rows = (
        await db.execute(
            select(Subscription).where(
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE, SubscriptionStatus.CANCELLED])
            )
        )
    ).scalars().all()
    expired = [s for s in rows if not subscription_grants_access(s)]
    for s in expired:
        s.status = SubscriptionStatus.EXPIRED
    await db.commit()
    return len(expired)


# -- tasks -----------------------------------------------------------------------------------------------


def _timed(name: str, coro_factory) -> None:
    try:
        run(coro_factory())
    except Exception:
        metrics.count("analytics_generation_failures_total")
        logger.exception("task %s failed", name)
        raise


@celery_app.task(name="app.worker.analytics_tasks.generate_predictions")
def generate_predictions() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            created = await generate_predictions_once(db, CacheAside(get_redis_service()))
        for match_id in created:
            _enqueue(notify_prediction_available, match_id)

    _timed("generate_predictions", _go)


@celery_app.task(name="app.worker.analytics_tasks.evaluate_predictions")
def evaluate_predictions() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await PredictionService(db).evaluate_finished()

    _timed("evaluate_predictions", _go)


@celery_app.task(name="app.worker.analytics_tasks.generate_insights")
def generate_insights() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await generate_insights_once(db, get_redis_service())

    _timed("generate_insights", _go)


@celery_app.task(name="app.worker.analytics_tasks.calculate_team_analytics")
def calculate_team_analytics() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await warm_team_analytics_once(db, CacheAside(get_redis_service()))

    _timed("calculate_team_analytics", _go)


@celery_app.task(name="app.worker.analytics_tasks.process_subscription_events")
def process_subscription_events() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await expire_lapsed_subscriptions_once(db)

    _timed("process_subscription_events", _go)


@celery_app.task(name="app.worker.analytics_tasks.notify_matchday")
def notify_matchday() -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await personal_insights.notify_matchday(db)
            await personal_insights.notify_polls_closing(db)

    _timed("notify_matchday", _go)


@celery_app.task(name="app.worker.analytics_tasks.notify_prediction_available", bind=True, max_retries=3)
def notify_prediction_available(self, match_id: int) -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await personal_insights.notify_prediction_available(db, match_id)

    try:
        run(_go())
    except Exception as exc:
        retry_or_raise(self, exc)


@celery_app.task(name="app.worker.analytics_tasks.notify_subscription_event", bind=True, max_retries=3)
def notify_subscription_event(self, user_id: int, kind: str, event_id: str) -> None:
    async def _go() -> None:
        async with AsyncSessionLocal() as db:
            await personal_insights.notify_subscription_event(db, user_id, kind, event_id)

    try:
        run(_go())
    except Exception as exc:
        retry_or_raise(self, exc)
