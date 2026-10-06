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
from app.events.schemas import RealtimeEventType
from app.models.competition import Competition
from app.models.enums import MatchStatus
from app.models.match import Match
from app.models.team import Team
from app.schemas.match import MatchDetail
from app.services.change_detection import build_state_snapshot, detect_changes
from app.services.football_service import FootballService
from app.services.match_centre_service import MatchCentreService
from app.services.providers import get_provider
from app.services.providers.base import FootballDataProvider
from app.services.team_player_service import TeamPlayerService
from app.worker.async_runner import run as _run
from app.worker.celery_app import celery_app
from app.worker.provider_guard import GuardedProvider, ProviderUnavailableError, call_with_backoff
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

_NEAR_KICKOFF_WINDOW = timedelta(minutes=15)
_POST_MATCH_WINDOW = timedelta(minutes=30)


# Events that only refresh an open match-centre screen. They are published
# to the WebSocket channel but never handed to the notification dispatcher.
_NON_NOTIFIABLE = {RealtimeEventType.LINEUP_UPDATED, RealtimeEventType.STATISTICS_UPDATED}


def _invalidate_after_finish(redis, match: MatchDetail) -> None:
    """A match just became FINISHED: the competition's table, top scorers
    and both teams' form/statistics are now out of date (Phase 4 §19), and
    a fresh standings sync is queued. Nothing here runs for in-play events
    -- a live goal doesn't change *official* standings."""
    redis.delete(
        RedisKeys.competition_standings(match.competition.id),
        RedisKeys.competition_top_scorers(match.competition.id),
        RedisKeys.competition_fixtures(match.competition.id, datetime.now(timezone.utc).date()),
        RedisKeys.team_form(match.home_team.id, "overall"),
        RedisKeys.team_form(match.home_team.id, "home"),
        RedisKeys.team_form(match.home_team.id, "away"),
        RedisKeys.team_form(match.away_team.id, "overall"),
        RedisKeys.team_form(match.away_team.id, "home"),
        RedisKeys.team_form(match.away_team.id, "away"),
        RedisKeys.team_statistics(match.home_team.id),
        RedisKeys.team_statistics(match.away_team.id),
        RedisKeys.team_fixtures(match.home_team.id),
        RedisKeys.team_fixtures(match.away_team.id),
    )
    try:
        sync_competition_standings.delay(match.competition.id)
    except Exception:
        logger.warning("Failed to enqueue sync_competition_standings for %s", match.competition.id, exc_info=True)


def _publish_changes(
    match: MatchDetail, *, lineup_fingerprint: str | None = None, statistics: dict | None = None
) -> None:
    # Deferred import: `notification_tasks` imports `celery_app`, which
    # (at module scope) imports `tasks` back for its own side effects --
    # importing it at call time instead of at this module's top avoids a
    # load-order-dependent circular import (whichever of the three modules
    # happens to be imported first).
    from app.worker.notification_tasks import dispatch_notifications

    redis = get_sync_redis_service()
    state_key = RedisKeys.match_state(match.id)
    previous = redis.get(state_key)
    changes = detect_changes(match, previous, lineup_fingerprint=lineup_fingerprint, statistics=statistics)
    redis.set(state_key, build_state_snapshot(match, lineup_fingerprint=lineup_fingerprint, statistics=statistics))
    # Invalidate the cache-aside entries this match affects so the next API
    # request sees the new state immediately instead of waiting out the TTL.
    redis.delete(RedisKeys.match(match.id), RedisKeys.LIVE_MATCHES, RedisKeys.TODAY_MATCHES)
    changed_types = {c.type for c in changes}
    # The lineup response embeds each player's substitution minutes (derived
    # from the timeline), so a new substitution stales it just like a
    # changed lineup does.
    if RealtimeEventType.LINEUP_UPDATED in changed_types or RealtimeEventType.SUBSTITUTION in changed_types:
        redis.delete(RedisKeys.match_lineups(match.id))
    if RealtimeEventType.STATISTICS_UPDATED in changed_types:
        redis.delete(RedisKeys.match_statistics(match.id), RedisKeys.match_player_statistics(match.id))
    if RealtimeEventType.MATCH_FINISHED in changed_types:
        # A finished match's cached lineups/stats carry the short live TTL;
        # drop them so the next read re-caches with the static one.
        redis.delete(
            RedisKeys.match_lineups(match.id),
            RedisKeys.match_statistics(match.id),
            RedisKeys.match_player_statistics(match.id),
        )
        _invalidate_after_finish(redis, match)

    for event in changes:
        logger.info("Match %s changed: %s", match.id, event.type.value)
        payload = event.model_dump(mode="json")
        redis.publish(RedisKeys.MATCH_EVENTS_CHANNEL, payload)
        if event.type in _NON_NOTIFIABLE:
            continue
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
        centre = MatchCentreService(db, GuardedProvider(provider), football=service)
        try:
            await centre.sync_match_extras(match)
        except ProviderUnavailableError:
            # Lineups/statistics are supplementary: the score/events sync
            # above already succeeded, so keep publishing that and pick the
            # extras up again next cycle.
            metrics.sync_job_failed()
            logger.error("match extras unavailable for %s; continuing without them", provider_match.provider_id)
        await db.commit()
        detail = await service.get_match(match.id)
        lineup_fingerprint = await centre.lineup_fingerprint(match.id)
        statistics = await centre.statistics_snapshot(match)
    _publish_changes(detail, lineup_fingerprint=lineup_fingerprint, statistics=statistics)


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
                try:
                    await TeamPlayerService(db, GuardedProvider(provider), service).sync_top_scorers(competition)
                except ProviderUnavailableError:
                    metrics.sync_job_failed()
            await db.commit()

    _run(_run_task())


@celery_app.task(name="app.worker.tasks.sync_team")
def sync_team(team_provider_id: str) -> None:
    """Team metadata + squad + fixtures sync (spec §7). Not on a fixed beat
    schedule -- enqueued on demand (following a team, or opening a team page
    whose squad hasn't been stored yet); the squad is what makes the team
    page's Squad section and player pages possible."""

    async def _run_task() -> None:
        provider = get_provider()
        metrics.sync_job_started()

        async with AsyncSessionLocal() as db:
            service = FootballService(db=db, provider=provider)
            team = (
                await db.execute(select(Team).where(Team.provider_id == team_provider_id))
            ).scalar_one_or_none()
            if team is not None and provider.capabilities.team_squads:
                try:
                    await TeamPlayerService(db, GuardedProvider(provider), service).sync_squad(team)
                    await db.commit()
                    get_sync_redis_service().delete(RedisKeys.team_squad(team.id), RedisKeys.team(team.id))
                except ProviderUnavailableError:
                    metrics.sync_job_failed()
                    logger.error("sync_team: squad unavailable for %s", team_provider_id)

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


@celery_app.task(name="app.worker.tasks.sync_player")
def sync_player(player_provider_id: str) -> None:
    """Player profile sync -- enqueued by the player page when a player only
    exists as a stub created from a match event or lineup."""

    async def _run_task() -> None:
        provider = get_provider()
        metrics.sync_job_started()
        async with AsyncSessionLocal() as db:
            try:
                player = await TeamPlayerService(db, GuardedProvider(provider)).sync_player(player_provider_id)
            except ProviderUnavailableError:
                metrics.sync_job_failed()
                logger.error("sync_player: provider unavailable for %s", player_provider_id)
                return
            await db.commit()
            if player is not None:
                get_sync_redis_service().delete(RedisKeys.player(player.id), RedisKeys.player_statistics(player.id))

    _run(_run_task())


async def sync_competition_standings_now(competition_id: int) -> None:
    """The body of `sync_competition_standings`, as a coroutine so it can be
    driven directly (tests, the end-to-end scenario) as well as by Celery."""
    provider = get_provider()
    metrics.sync_job_started()
    async with AsyncSessionLocal() as db:
        competition = (
            await db.execute(select(Competition).where(Competition.id == competition_id))
        ).scalar_one_or_none()
        if competition is None:
            return
        guarded = GuardedProvider(provider)
        service = FootballService(db=db, provider=guarded)
        try:
            await service.sync_standings(competition)
            await TeamPlayerService(db, guarded, service).sync_top_scorers(competition)
        except ProviderUnavailableError:
            metrics.sync_job_failed()
            logger.error("sync_competition_standings: provider unavailable for %s", competition_id)
            return
        await db.commit()
    get_sync_redis_service().delete(
        RedisKeys.competition_standings(competition_id), RedisKeys.competition_top_scorers(competition_id)
    )


@celery_app.task(name="app.worker.tasks.sync_competition_standings")
def sync_competition_standings(competition_id: int) -> None:
    """Standings + top scorers for ONE competition (Phase 4 §19). Queued by
    change detection when a match in the competition becomes FINISHED --
    standings are based on completed matches, so live goals don't trigger a
    re-sync; the periodic `sync_competitions` job remains the backstop."""
    _run(sync_competition_standings_now(competition_id))


async def sync_competition_season_now(competition_id: int, season: str) -> None:
    """Backfill one *past* season's standings and top scorers (Phase 5),
    queued when a client asks for a season we haven't stored."""
    provider = get_provider()
    metrics.sync_job_started()
    async with AsyncSessionLocal() as db:
        competition = (
            await db.execute(select(Competition).where(Competition.id == competition_id))
        ).scalar_one_or_none()
        if competition is None:
            return
        guarded = GuardedProvider(provider)
        service = FootballService(db=db, provider=guarded)
        try:
            await service.sync_standings(competition, season=season)
            await TeamPlayerService(db, guarded, service).sync_top_scorers(competition, season=season)
        except ProviderUnavailableError:
            metrics.sync_job_failed()
            logger.error("sync_competition_season: provider unavailable for %s %s", competition_id, season)
            return
        await db.commit()
    get_sync_redis_service().delete(
        RedisKeys.competition_standings(competition_id, season),
        RedisKeys.competition_top_scorers(competition_id, season),
        RedisKeys.competition_seasons(competition_id),
    )


@celery_app.task(name="app.worker.tasks.sync_competition_season")
def sync_competition_season(competition_id: int, season: str) -> None:
    """On-demand history backfill for one competition season."""
    _run(sync_competition_season_now(competition_id, season))
