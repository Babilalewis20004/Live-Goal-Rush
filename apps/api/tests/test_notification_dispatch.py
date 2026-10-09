"""Notification dispatch tests (Phase 3 §31): preference-matching fan-out,
opt-out/global-mute overrides, default-on vs default-off event types, and
dedup-on-redelivery. Feeds synthetic `RealtimeEvent` payloads straight into
`resolve_targets` against seeded favourites/preferences -- unit-level, no
HTTP or Celery involved (matching `test_event_dedup.py`'s style of syncing
directly via `FootballService` for full control over ids).
"""

from datetime import datetime, timezone

from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.events.schemas import RealtimeEvent, RealtimeEventType
from app.models.enums import NotificationScope
from app.models.favourite import FavouriteCompetition, FavouriteMatch, FavouriteTeam
from app.models.notification import NotificationLog, NotificationPreference
from app.models.user import User
from app.services.football_service import FootballService
from app.services.notification_dispatch_service import resolve_targets
from tests.fakes.mock_provider import MockFootballDataProvider
from app.services.providers.schemas import ProviderCompetition, ProviderMatch, ProviderTeam

_COMPETITION = ProviderCompetition(provider_id="comp-x", name="Test League", country="Testland", type="league")
_HOME = ProviderTeam(provider_id="team-home", name="Home FC", short_name="HOM", country="Testland")
_AWAY = ProviderTeam(provider_id="team-away", name="Away FC", short_name="AWY", country="Testland")


def _provider_match() -> ProviderMatch:
    return ProviderMatch(
        provider_id="match-x",
        competition=_COMPETITION,
        home_team=_HOME,
        away_team=_AWAY,
        kickoff_time=datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc),
        status="live",
        home_score=1,
        away_score=0,
        minute=50,
        events=[],
    )


async def _seed_match(session):
    service = FootballService(db=session, provider=MockFootballDataProvider())
    match = await service.sync_match(_provider_match())
    await session.commit()
    return match


async def _make_user(session, email: str) -> User:
    user = User(email=email, hashed_password="x")
    session.add(user)
    await session.flush()
    return user


def _goal_event(match_id: int, event_id: int = 1) -> RealtimeEvent:
    return RealtimeEvent(
        type=RealtimeEventType.GOAL,
        match_id=str(match_id),
        data={"home_score": 1, "away_score": 0, "status": "live", "minute": 50, "event": {"id": event_id}},
    )


async def test_fanout_across_team_and_competition_favourites(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user_a = await _make_user(session, "a@example.com")  # follows home team
        user_b = await _make_user(session, "b@example.com")  # follows the competition
        user_c = await _make_user(session, "c@example.com")  # follows nothing relevant
        session.add(FavouriteTeam(user_id=user_a.id, team_id=match.home_team_id))
        session.add(FavouriteCompetition(user_id=user_b.id, competition_id=match.competition_id))
        await session.commit()

        targets = await resolve_targets(session, _goal_event(match.id))
        notified_ids = {t.user_id for t in targets}

    assert notified_ids == {user_a.id, user_b.id}
    assert user_c.id not in notified_ids


async def test_explicit_team_scope_opt_out_excludes_user(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = await _make_user(session, "muted@example.com")
        session.add(FavouriteTeam(user_id=user.id, team_id=match.home_team_id))
        session.add(
            NotificationPreference(
                user_id=user.id,
                scope_type=NotificationScope.TEAM,
                scope_id=match.home_team_id,
                event_type=RealtimeEventType.GOAL,
                enabled=False,
            )
        )
        await session.commit()

        targets = await resolve_targets(session, _goal_event(match.id))

    assert targets == []


async def test_global_mute_overrides_every_qualifying_scope(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = await _make_user(session, "globalmute@example.com")
        # Qualifies via BOTH team and competition follows...
        session.add(FavouriteTeam(user_id=user.id, team_id=match.home_team_id))
        session.add(FavouriteCompetition(user_id=user.id, competition_id=match.competition_id))
        # ...but a GLOBAL mute for this event type wins outright.
        session.add(
            NotificationPreference(
                user_id=user.id,
                scope_type=NotificationScope.GLOBAL,
                scope_id=None,
                event_type=RealtimeEventType.GOAL,
                enabled=False,
            )
        )
        await session.commit()

        targets = await resolve_targets(session, _goal_event(match.id))

    assert targets == []


async def test_default_off_event_type_requires_explicit_opt_in(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = await _make_user(session, "substitution@example.com")
        session.add(FavouriteTeam(user_id=user.id, team_id=match.home_team_id))
        await session.commit()

        substitution_event = RealtimeEvent(
            type=RealtimeEventType.SUBSTITUTION,
            match_id=str(match.id),
            data={"home_score": 1, "away_score": 0, "status": "live", "minute": 60, "event": {"id": 2}},
        )
        # No preference row yet -- SUBSTITUTION is default-off.
        no_targets = await resolve_targets(session, substitution_event)
        assert no_targets == []

        session.add(
            NotificationPreference(
                user_id=user.id,
                scope_type=NotificationScope.TEAM,
                scope_id=match.home_team_id,
                event_type=RealtimeEventType.SUBSTITUTION,
                enabled=True,
            )
        )
        await session.commit()

        opted_in_targets = await resolve_targets(session, substitution_event)

    assert [t.user_id for t in opted_in_targets] == [user.id]


async def test_redelivered_event_is_deduplicated(test_engine: AsyncEngine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        user = await _make_user(session, "dedup@example.com")
        session.add(FavouriteMatch(user_id=user.id, match_id=match.id))
        await session.commit()

        event = _goal_event(match.id, event_id=42)
        first_pass = await resolve_targets(session, event)
        second_pass = await resolve_targets(session, event)  # e.g. a Celery retry, or provider resend

        log_rows = await session.execute(
            NotificationLog.__table__.select().where(NotificationLog.user_id == user.id)
        )

    assert len(first_pass) == 1
    assert second_pass == []
    assert len(log_rows.fetchall()) == 1


async def test_query_count_does_not_grow_with_unrelated_users(test_engine: AsyncEngine):
    """Not O(all users): seeds a pile of users with no relation to this
    match and confirms `resolve_targets` still issues the same small,
    fixed number of statements -- the three favourite-table lookups filter
    on this match's ids directly rather than scanning every user."""
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        match = await _seed_match(session)
        follower = await _make_user(session, "follower@example.com")
        session.add(FavouriteTeam(user_id=follower.id, team_id=match.home_team_id))
        for i in range(50):
            await _make_user(session, f"noise{i}@example.com")
        await session.commit()

        statement_count = 0

        def _count(*_args, **_kwargs):
            nonlocal statement_count
            statement_count += 1

        sa_event.listen(test_engine.sync_engine, "before_cursor_execute", _count)
        try:
            targets = await resolve_targets(session, _goal_event(match.id, event_id=99))
        finally:
            sa_event.remove(test_engine.sync_engine, "before_cursor_execute", _count)

    assert [t.user_id for t in targets] == [follower.id]
    # A handful of fixed statements (match lookup, 3 favourite-table scans,
    # preference lookup, dedup insert) -- nowhere near "one per user".
    assert statement_count <= 8
