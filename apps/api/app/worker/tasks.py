"""Background sync jobs (Phase 2 §6/§7/§8).

Every task here follows the same shape: run one or more provider calls
(guarded by `provider_guard.call_with_backoff`), upsert the result into
Postgres via `FootballService` (idempotent -- spec §24), then run change
detection and publish to Redis Pub/Sub for anything that meaningfully
changed (spec §11/§13). Tasks never talk to WebSocket connections directly
-- that's `app/websocket/pubsub_bridge.py`'s job, in the API process.

Each task opens its own `AsyncSessionLocal` and runs on a persistent
per-worker-process event loop (see `app.worker.async_runner.run`) --
Celery's task execution model is synchronous, so this is the bridge into
the same async DB/provider code the API uses, rather than a second
implementation of it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.redis_client import get_sync_redis_service
from app.core.redis_keys import RedisKeys
from app.db.session import AsyncSessionLocal
from app.models.enums import MatchStatus
from app.models.match import Match
from app.schemas.match import MatchDetail
from app.services.change_detection import build_state_snapshot, detect_changes
from app.services.football_service import FootballService
from app.services.providers import get_provider
from app.services.providers.base import FootballDataProvider
from app.worker.async_runner import run as _run
from app.worker.celery_app import celery_app
from app.worker.provider_guard import ProviderUnavailableError, call_with_backoff
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

_NEAR_KICKOFF_WINDOW = timedelta(minutes=15)
_POST_MATCH_WINDOW = timedelta(minutes=30)


def _publish_changes(match: MatchDetail) -> None:
    # Deferred import: `notification_tasks` imports `celery_app`, which
    # (at module scope) imports `tasks` back for its own side effects --
    # importing it at call time instead of at this module's top avoids a
    # load-order-dependent circular import (whichever of the three modules
    # happens to be imported first).
    from app.worker.notification_tasks import dispatch_notifications

    redis = get_sync_redis_service()
    state_key = RedisKeys.match_state(match.id)
    previous = redis.get(state_key)
    changes = detect_changes(match, previous)
    redis.set(state_key, build_state_snapshot(match))
    # Invalidate the cache-aside entries this match affects so the next API
    # request sees the new state immediately instead of waiting out the TTL.
    redis.delete(RedisKeys.match(match.id), RedisKeys.LIVE_MATCHES, RedisKeys.TODAY_MATCHES)

    for event in changes:
        logger.info("Match %s changed: %s", match.id, event.type.value)
        payload = event.model_dump(mode="json")
        redis.publish(RedisKeys.MATCH_EVENTS_CHANNEL, payload)
        # A second, independent consumer of the same event (Phase 3 §12) --
        # dispatched as its own Celery task (not called inline) so a slow
        # or failing push provider can never slow down or crash the live
        # sync loop, and gets its own retry semantics separate from
        # provider-sync retries.
        try:
            dispatch_notifications.delay(payload)
        except Exception:
            logger.warning("Failed to enqueue dispatch_notifications for match %s", match.id, exc_info=True)


async def _sync_one_match(provider: FootballDataProvider, provider_match) -> None:
    async with AsyncSessionLocal() as db:
        service = FootballService(db=db, provider=provider)
        match = await service.sync_match(provider_match, with_events=True)
        await db.commit()
        detail = await service.get_match(match.id)
    _publish_changes(detail)


@celery_app.task(name="app.worker.tasks.sync_live_matches")
def sync_live_matches() -> None:
    """The adaptive-polling core (spec §8/§9): runs every
    LIVE_POLL_INTERVAL_SECONDS via Celery beat, asks the provider for
    exactly the matches it considers live right now (not every historical
    match), and syncs+publishes each one. A match that has just gone
    LIVE/HALFTIME->FINISHED falls out of this list on its own on the next
    cycle -- there's no separate "stop polling" step needed."""

    async def _run_task() -> None:
        provider = get_provider()
        metrics.sync_job_started()
        try:
            provider_matches = await call_with_backoff("get_live_matches", provider.get_live_matches)
        except ProviderUnavailableError:
            metrics.sync_job_failed()
            logger.error("sync_live_matches: provider unavailable, skipping this cycle")
            return

        metrics.set_live_matches(len(provider_matches))
        for provider_match in provider_matches:
            await _sync_one_match(provider, provider_match)

    _run(_run_task())


@celery_app.task(name="app.worker.tasks.sync_upcoming_kickoffs")
def sync_upcoming_kickoffs() -> None:
    """Moderate-frequency check (spec §9's "5-15 minutes before kickoff")
    for matches the database still thinks are SCHEDULED but whose kickoff
    is imminent -- these are the ones most likely to have just gone LIVE
    since the last full fixtures sync. DB-driven match selection (spec §8):
    the provider has no "matches near kickoff" query, so this is exactly
    where reading Postgres first, then targeting individual `get_match`
    calls, matters."""

    async def _run_task() -> None:
        provider = get_provider()
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            stmt = select(Match).where(
                Match.status == MatchStatus.SCHEDULED,
                Match.kickoff_time <= now + _NEAR_KICKOFF_WINDOW,
                Match.kickoff_time >= now - _NEAR_KICKOFF_WINDOW,
            )
            near_kickoff = (await db.execute(stmt)).scalars().all()
            provider_ids = [m.provider_id for m in near_kickoff]

        metrics.sync_job_started()
        for provider_id in provider_ids:
            try:
                provider_match = await call_with_backoff(
                    "get_match", lambda pid=provider_id: provider.get_match(pid)
                )
            except ProviderUnavailableError:
                metrics.sync_job_failed()
                logger.error("sync_upcoming_kickoffs: provider unavailable for %s", provider_id)
                continue
            if provider_match is not None:
                await _sync_one_match(provider, provider_match)

    _run(_run_task())


@celery_app.task(name="app.worker.tasks.sync_post_match")
def sync_post_match() -> None:
    """Catches late provider corrections to a match shortly after full time
    (spec §9's "Full time -> Stop live polling" -- this is the brief tail
    of moderate-frequency checking before polling stops altogether)."""

    async def _run_task() -> None:
        provider = get_provider()
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            stmt = select(Match).where(
                Match.status == MatchStatus.FINISHED,
                Match.last_synced_at.isnot(None),
                Match.last_synced_at >= now - _POST_MATCH_WINDOW,
            )
            recently_finished = (await db.execute(stmt)).scalars().all()
            provider_ids = [m.provider_id for m in recently_finished]

        metrics.sync_job_started()
        for provider_id in provider_ids:
            try:
                provider_match = await call_with_backoff(
                    "get_match", lambda pid=provider_id: provider.get_match(pid)
                )
            except ProviderUnavailableError:
                metrics.sync_job_failed()
                logger.error("sync_post_match: provider unavailable for %s", provider_id)
                continue
            if provider_match is not None:
                await _sync_one_match(provider, provider_match)

    _run(_run_task())


@celery_app.task(name="app.worker.tasks.sync_fixtures")
def sync_fixtures() -> None:
    """Fixtures sync (spec §7): today, tomorrow, the upcoming window, and
    yesterday's results (recent results), across every known competition."""

    async def _run_task() -> None:
        provider = get_provider()
        today = datetime.now(timezone.utc).date()
        metrics.sync_job_started()

        for offset in range(-1, 8):  # yesterday .. 7 days out
            on_date = today + timedelta(days=offset)
            try:
                provider_matches = await call_with_backoff(
                    f"get_fixtures({on_date})", lambda d=on_date: provider.get_fixtures(d)
                )
            except ProviderUnavailableError:
                metrics.sync_job_failed()
                logger.error("sync_fixtures: provider unavailable for %s", on_date)
                continue

            async with AsyncSessionLocal() as db:
                service = FootballService(db=db, provider=provider)
                for provider_match in provider_matches:
                    await service.sync_match(provider_match, with_events=True)
                await db.commit()

    _run(_run_task())


@celery_app.task(name="app.worker.tasks.sync_competitions")
def sync_competitions() -> None:
    """Competition metadata, fixtures and standings sync (spec §7)."""

    async def _run_task() -> None:
        provider = get_provider()
        metrics.sync_job_started()
        try:
            provider_competitions = await call_with_backoff("get_competitions", provider.get_competitions)
        except ProviderUnavailableError:
            metrics.sync_job_failed()
            logger.error("sync_competitions: provider unavailable")
            return

        async with AsyncSessionLocal() as db:
            service = FootballService(db=db, provider=provider)
            for provider_competition in provider_competitions:
                competition = await service._sync_competition(provider_competition)
                try:
                    fixtures = await call_with_backoff(
                        f"get_competition_fixtures({provider_competition.provider_id})",
                        lambda cid=provider_competition.provider_id: provider.get_competition_fixtures(cid),
                    )
                except ProviderUnavailableError:
                    metrics.sync_job_failed()
                    continue
                for provider_match in fixtures:
                    await service.sync_match(provider_match, with_events=True)
                await service.sync_standings(competition)
            await db.commit()

    _run(_run_task())


@celery_app.task(name="app.worker.tasks.sync_team")
def sync_team(team_provider_id: str) -> None:
    """Team metadata + fixtures sync (spec §7). Not on a fixed beat
    schedule -- enqueued on demand (e.g. a Phase 3 "follow this team"
    feature would call `sync_team.delay(team_id)`); included now so the
    capability exists without over-scheduling it for Phase 2's needs."""

    async def _run_task() -> None:
        provider = get_provider()
        metrics.sync_job_started()
        try:
            fixtures = await call_with_backoff(
                f"get_team_fixtures({team_provider_id})",
                lambda: provider.get_team_fixtures(team_provider_id),
            )
        except ProviderUnavailableError:
            metrics.sync_job_failed()
            logger.error("sync_team: provider unavailable for %s", team_provider_id)
            return

        async with AsyncSessionLocal() as db:
            service = FootballService(db=db, provider=provider)
            for provider_match in fixtures:
                await service.sync_match(provider_match, with_events=True)
            await db.commit()

    _run(_run_task())
