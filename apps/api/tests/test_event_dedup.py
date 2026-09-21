"""Match sync idempotency and event dedup (Phase 2 §24/§25): running the
same sync twice must not duplicate matches or events, and an event's
database id must stay stable across polls (change detection depends on
this -- see test_change_detection.py)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models.match_event import MatchEvent
from app.services.football_service import FootballService
from app.services.providers.mock_provider import MockFootballDataProvider
from app.services.providers.schemas import (
    ProviderCompetition,
    ProviderMatch,
    ProviderMatchEvent,
    ProviderTeam,
)

_COMPETITION = ProviderCompetition(provider_id="comp-x", name="Test League", country="Testland", type="league")
_HOME = ProviderTeam(provider_id="team-home", name="Home FC", short_name="HOM", country="Testland")
_AWAY = ProviderTeam(provider_id="team-away", name="Away FC", short_name="AWY", country="Testland")


def _provider_match(*, events: list[ProviderMatchEvent], home_score=0, away_score=0) -> ProviderMatch:
    return ProviderMatch(
        provider_id="match-x",
        competition=_COMPETITION,
        home_team=_HOME,
        away_team=_AWAY,
        kickoff_time=datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc),
        status="live",
        home_score=home_score,
        away_score=away_score,
        minute=50,
        events=events,
    )


async def _events_for(session, match_id: int) -> list[MatchEvent]:
    result = await session.execute(select(MatchEvent).where(MatchEvent.match_id == match_id))
    return list(result.scalars().all())


async def test_syncing_the_same_match_twice_does_not_duplicate_it(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    provider = MockFootballDataProvider()
    provider_match = _provider_match(events=[])

    async with session_local() as session:
        service = FootballService(db=session, provider=provider)
        match1 = await service.sync_match(provider_match)
        await session.commit()
        match2 = await service.sync_match(provider_match)
        await session.commit()

    assert match1.id == match2.id


async def test_events_with_provider_ids_upsert_in_place_without_duplicating(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    provider = MockFootballDataProvider()
    events = [
        ProviderMatchEvent(provider_id="ev-1", event_type="goal", minute=10, team=_HOME),
        ProviderMatchEvent(provider_id="ev-2", event_type="yellow_card", minute=30, team=_AWAY),
    ]

    async with session_local() as session:
        service = FootballService(db=session, provider=provider)
        match = await service.sync_match(_provider_match(events=events, home_score=1), with_events=True)
        await session.commit()
        first_sync_events = await _events_for(session, match.id)
        first_ids = {e.id for e in first_sync_events}
        assert len(first_ids) == 2

        # Re-sync the identical payload -- must not create new rows.
        await service.sync_match(_provider_match(events=events, home_score=1), with_events=True)
        await session.commit()
        second_sync_events = await _events_for(session, match.id)
        assert {e.id for e in second_sync_events} == first_ids


async def test_removed_event_is_deleted_and_remaining_ids_stay_stable(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    provider = MockFootballDataProvider()
    events = [
        ProviderMatchEvent(provider_id="ev-1", event_type="goal", minute=10, team=_HOME),
        ProviderMatchEvent(provider_id="ev-2", event_type="yellow_card", minute=30, team=_AWAY),
    ]

    async with session_local() as session:
        service = FootballService(db=session, provider=provider)
        match = await service.sync_match(_provider_match(events=events, home_score=1), with_events=True)
        await session.commit()
        goal_id = next(e.id for e in await _events_for(session, match.id) if e.event_type.value == "goal")

        # Provider correction: the card is retracted (e.g. VAR overturn).
        remaining = [events[0]]
        await service.sync_match(_provider_match(events=remaining, home_score=1), with_events=True)
        await session.commit()

        final_events = await _events_for(session, match.id)
        assert len(final_events) == 1
        assert final_events[0].id == goal_id


async def test_events_without_provider_ids_still_dedup_via_synthetic_key(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    provider = MockFootballDataProvider()
    events = [ProviderMatchEvent(provider_id=None, event_type="goal", minute=10, team=_HOME)]

    async with session_local() as session:
        service = FootballService(db=session, provider=provider)
        match = await service.sync_match(_provider_match(events=events, home_score=1), with_events=True)
        await session.commit()
        first_ids = {e.id for e in await _events_for(session, match.id)}

        await service.sync_match(_provider_match(events=events, home_score=1), with_events=True)
        await session.commit()
        second_ids = {e.id for e in await _events_for(session, match.id)}

        assert first_ids == second_ids
        assert len(first_ids) == 1
