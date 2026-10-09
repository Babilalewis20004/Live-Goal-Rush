"""Phase 4 synchronization: lineups/statistics sync is idempotent, honours
provider capabilities, never deletes on an empty answer, and tolerates
provider quirks (unknown event types, retries)."""

import httpx
import pytest
from sqlalchemy import func, select

from app.models.lineup import LineupPlayer, MatchLineup
from app.models.match import Match
from app.models.match_event import MatchEvent
from app.models.statistics import MatchStatistic, PlayerMatchStatistic
from app.services.football_service import FootballService
from app.services.match_centre_service import MatchCentreService
from app.services.providers.base import FootballDataProvider
from tests.fakes.mock_provider import MockFootballDataProvider
from app.services.providers.real_provider import RealFootballDataProvider
from app.services.providers.schemas import ProviderCapabilities
from app.worker.provider_guard import GuardedProvider, ProviderUnavailableError


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _finished_match(session, provider_id="epl-3") -> Match:
    return (await session.execute(select(Match).where(Match.provider_id == provider_id))).scalar_one()


# -- idempotency / duplicate prevention ----------------------------------------------------------


async def test_repeated_extras_sync_creates_no_duplicates(seeded_client, session_factory):
    provider = MockFootballDataProvider()
    async with session_factory() as session:
        match = await _finished_match(session)
        centre = MatchCentreService(session, provider)
        await centre.sync_match_extras(match)
        await session.commit()
        first = [await _count(session, m) for m in (MatchLineup, LineupPlayer, MatchStatistic, PlayerMatchStatistic)]

        for _ in range(3):
            await centre.sync_lineups(match)
            await centre.sync_statistics(match)
            await centre.sync_player_statistics(match)
        await session.commit()
        again = [await _count(session, m) for m in (MatchLineup, LineupPlayer, MatchStatistic, PlayerMatchStatistic)]

    assert first == again
    assert first[0] == 2 and first[1] == 36 and first[2] == 2 and first[3] >= 22


async def test_fingerprint_is_stable_across_resyncs_and_changes_with_the_lineup(seeded_client, session_factory):
    provider = MockFootballDataProvider()
    async with session_factory() as session:
        match = await _finished_match(session)
        centre = MatchCentreService(session, provider)
        assert await centre.lineup_fingerprint(match.id) is None  # nothing stored yet
        await centre.sync_lineups(match)
        first = await centre.lineup_fingerprint(match.id)
        await centre.sync_lineups(match)
        assert await centre.lineup_fingerprint(match.id) == first

        class _Reshuffled(MockFootballDataProvider):
            async def get_lineups(self, match_id):
                lineups = await super().get_lineups(match_id)
                lineups[0].formation = "3-5-2"
                return lineups

        await MatchCentreService(session, _Reshuffled()).sync_lineups(match)
        assert await centre.lineup_fingerprint(match.id) != first


async def test_lineup_players_dropped_by_the_provider_are_removed(seeded_client, session_factory):
    async with session_factory() as session:
        match = await _finished_match(session)
        await MatchCentreService(session, MockFootballDataProvider()).sync_lineups(match)

        class _TrimmedBench(MockFootballDataProvider):
            async def get_lineups(self, match_id):
                lineups = await super().get_lineups(match_id)
                for lu in lineups:
                    lu.players = lu.players[:15]
                return lineups

        await MatchCentreService(session, _TrimmedBench()).sync_lineups(match)
        await session.commit()
        assert await _count(session, LineupPlayer) == 30


async def test_statistics_snapshot_reflects_stored_values(seeded_client, session_factory):
    async with session_factory() as session:
        match = await _finished_match(session)
        centre = MatchCentreService(session, MockFootballDataProvider())
        assert await centre.statistics_snapshot(match) is None
        await centre.sync_statistics(match)
        snapshot = await centre.statistics_snapshot(match)
    assert set(snapshot) == {"home", "away"}
    assert snapshot["home"]["team_id"] == match.home_team_id
    assert snapshot["home"]["expected_goals"] is None


# -- capabilities / graceful absence -----------------------------------------------------------------


class _NoExtras(FootballDataProvider):
    """A provider that supports none of the Phase 4 extras -- like the real
    provider's free tier. It inherits the default (unsupported) methods."""

    async def get_live_matches(self): return []  # noqa: E704
    async def get_fixtures(self, on_date): return []  # noqa: E704
    async def get_match(self, match_id): return None  # noqa: E704
    async def get_competitions(self): return []  # noqa: E704
    async def get_competition_fixtures(self, competition_id): return []  # noqa: E704
    async def get_standings(self, competition_id): return []  # noqa: E704
    async def get_team(self, team_id): return None  # noqa: E704
    async def get_team_fixtures(self, team_id): return []  # noqa: E704
    async def search(self, query): raise AssertionError("unused")  # noqa: E704


async def test_unsupported_provider_syncs_nothing_and_raises_nothing(seeded_client, session_factory):
    provider = _NoExtras()
    assert provider.capabilities == ProviderCapabilities()  # all extras off; standings on
    async with session_factory() as session:
        match = await _finished_match(session)
        centre = MatchCentreService(session, provider)
        assert await centre.sync_lineups(match) is False
        assert await centre.sync_statistics(match) is False
        assert await centre.sync_player_statistics(match) is False
        await centre.sync_match_extras(match)
        assert await _count(session, MatchLineup) == 0
        assert await _count(session, MatchStatistic) == 0


async def test_capability_flag_is_honoured_even_if_the_method_returns_data(seeded_client, session_factory):
    class _Declines(MockFootballDataProvider):
        @property
        def capabilities(self):
            return ProviderCapabilities(lineups=False, match_statistics=False, player_statistics=False)

    async with session_factory() as session:
        match = await _finished_match(session)
        await MatchCentreService(session, _Declines()).sync_match_extras(match)
        assert await _count(session, MatchLineup) == 0


async def test_empty_provider_answer_does_not_delete_stored_data(seeded_client, session_factory):
    async with session_factory() as session:
        match = await _finished_match(session)
        await MatchCentreService(session, MockFootballDataProvider()).sync_match_extras(match)

        class _TransientlyEmpty(MockFootballDataProvider):
            async def get_lineups(self, match_id): return []  # noqa: E704
            async def get_match_statistics(self, match_id): return []  # noqa: E704

        await MatchCentreService(session, _TransientlyEmpty()).sync_lineups(match)
        await MatchCentreService(session, _TransientlyEmpty()).sync_statistics(match)
        await session.commit()
        assert await _count(session, LineupPlayer) == 36
        assert await _count(session, MatchStatistic) == 2


async def test_unavailable_features_answer_200_with_empty_payloads(seeded_client, get_match_id):
    """Nothing was synced (no phase4 fixture): every Phase 4 read is a 200
    with explicit "nothing here" data -- never a 404/500 for a real match."""
    match_id = await get_match_id("epl-3")
    assert (await seeded_client.get(f"/api/v1/matches/{match_id}/lineups")).json() == {"home": None, "away": None}
    assert (await seeded_client.get(f"/api/v1/matches/{match_id}/statistics")).json() == {"home": None, "away": None}
    assert (await seeded_client.get(f"/api/v1/matches/{match_id}/players")).json() == {"players": []}


# -- normalization ----------------------------------------------------------------------------------------


async def test_unknown_provider_event_types_are_skipped_not_fatal(seeded_client, session_factory):
    class _WeirdEvents(MockFootballDataProvider):
        async def get_match(self, match_id):
            match = await super().get_match(match_id)
            bad = match.events[0].model_copy(update={"provider_id": "weird-1", "event_type": "hologram_goal"})
            match.events = [*match.events, bad]
            return match

    provider = _WeirdEvents()
    async with session_factory() as session:
        provider_match = await provider.get_match("epl-3")
        match = await FootballService(session, provider).sync_match(provider_match, with_events=True)
        await session.commit()
        stored = (await session.execute(select(MatchEvent).where(MatchEvent.match_id == match.id))).scalars().all()
    assert len(stored) == 5  # epl-3's five real events; the unsupported one is dropped
    assert all(e.provider_id != "weird-1" for e in stored)


async def test_event_detail_round_trips_through_normalization(seeded_client, session_factory):
    class _Detailed(MockFootballDataProvider):
        async def get_match(self, match_id):
            match = await super().get_match(match_id)
            match.events[0].event_detail = "Header"
            return match

    provider = _Detailed()
    async with session_factory() as session:
        match = await FootballService(session, provider).sync_match(await provider.get_match("epl-3"), with_events=True)
        await session.commit()
        first = (
            (await session.execute(select(MatchEvent).where(MatchEvent.match_id == match.id).order_by(MatchEvent.minute)))
            .scalars()
            .first()
        )
    assert first.event_detail == "Header"


# -- retries -----------------------------------------------------------------------------------------------------


@pytest.fixture
def fast_backoff(monkeypatch):
    from app.core.config import settings

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(settings, "sync_max_retries", 3)
    monkeypatch.setattr("app.worker.provider_guard.asyncio.sleep", _no_sleep)


async def test_guarded_provider_retries_then_succeeds(fast_backoff):
    class _Flaky(MockFootballDataProvider):
        calls = 0

        async def get_lineups(self, match_id):
            type(self).calls += 1
            if type(self).calls < 3:
                raise httpx.ConnectError("boom")
            return await super().get_lineups(match_id)

    guarded = GuardedProvider(_Flaky())
    lineups = await guarded.get_lineups("epl-3")
    assert _Flaky.calls == 3 and len(lineups) == 2


async def test_guarded_provider_gives_up_with_provider_unavailable(fast_backoff):
    class _Down(MockFootballDataProvider):
        calls = 0

        async def get_match_statistics(self, match_id):
            type(self).calls += 1
            raise httpx.ConnectError("down")

    with pytest.raises(ProviderUnavailableError):
        await GuardedProvider(_Down()).get_match_statistics("epl-3")
    assert _Down.calls == 3


async def test_guarded_provider_exposes_the_inner_capabilities():
    assert GuardedProvider(MockFootballDataProvider()).capabilities.lineups is True
    assert GuardedProvider(_NoExtras()).capabilities.lineups is False


# -- real provider mapping (football-data.org shapes, no network) ---------------------------------------------------


def _real(handler) -> RealFootballDataProvider:
    provider = RealFootballDataProvider(base_url="https://api.test/v4", api_key="k")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test/v4")
    return provider


def test_real_provider_declares_what_the_free_tier_lacks():
    caps = _real(lambda r: httpx.Response(200)).capabilities
    assert (caps.lineups, caps.match_statistics, caps.player_statistics, caps.match_events) == (False,) * 4
    assert (caps.standings, caps.top_scorers, caps.team_squads, caps.player_profiles, caps.venues) == (True,) * 5


async def test_real_provider_maps_standings_with_season_groups_and_form():
    def handler(request):
        assert request.url.path == "/v4/competitions/2021/standings"
        team = {"id": 57, "name": "Arsenal FC", "tla": "ARS", "crest": "x.png"}
        return httpx.Response(
            200,
            json={
                "season": {"startDate": "2025-08-15", "endDate": "2026-05-24"},
                "standings": [
                    {"type": "TOTAL", "group": None, "table": [
                        {"position": 1, "team": team, "playedGames": 8, "form": "W,W,D,L,W", "won": 6,
                         "draw": 1, "lost": 1, "points": 19, "goalsFor": 19, "goalsAgainst": 8}]},
                    {"type": "HOME", "table": [{"position": 9, "team": team}]},
                    {"type": "TOTAL", "group": "GROUP_B", "table": [
                        {"position": 2, "team": team, "playedGames": 6, "won": 3, "draw": 2, "lost": 1,
                         "points": 11, "goalsFor": 9, "goalsAgainst": 5}]},
                ],
            },
        )

    rows = await _real(handler).get_standings("2021")
    assert [(r.group, r.position, r.season) for r in rows] == [(None, 1, "2025/26"), ("Group B", 2, "2025/26")]
    assert rows[0].form == "WWDLW" and rows[1].form is None
    assert all(r.description is None for r in rows)  # qualification zones are never invented


async def test_real_provider_maps_top_scorers_squad_and_player():
    team_json = {"id": 57, "name": "Arsenal FC", "tla": "ARS", "venue": "Emirates Stadium"}

    def handler(request):
        path = request.url.path
        if path.endswith("/scorers"):
            return httpx.Response(200, json={
                "season": {"startDate": "2025-08-15", "endDate": "2026-05-24"},
                "scorers": [{"player": {"id": 9, "name": "A. Striker", "section": "Offence", "nationality": "Norway",
                                        "dateOfBirth": "2000-01-01"},
                             "team": team_json, "playedMatches": 8, "goals": 9, "assists": 2, "penalties": 3}]})
        if path == "/v4/teams/57":
            return httpx.Response(200, json={**team_json, "squad": [
                {"id": 1, "name": "G. Keeper", "position": "Goalkeeper", "nationality": "Spain", "dateOfBirth": "1990-01-01"},
                {"id": 2, "name": "C. Back", "position": "Centre-Back", "nationality": "Brazil"},
                {"id": 3, "name": "W. Ing", "position": "Left Winger", "nationality": "England"}]})
        if path == "/v4/persons/2":
            return httpx.Response(200, json={"id": 2, "name": "C. Back", "position": "Defence",
                                             "nationality": "Brazil", "currentTeam": team_json})
        return httpx.Response(404)

    provider = _real(handler)
    scorer = (await provider.get_top_scorers("2021"))[0]
    assert (scorer.goals, scorer.assists, scorer.appearances, scorer.penalties) == (9, 2, 8, 3)
    assert scorer.player.position == "Forward" and scorer.season == "2025/26"
    assert scorer.team.venue == "Emirates Stadium"

    squad = await provider.get_team_squad("57")
    assert [(p.name, p.position) for p in squad] == [
        ("G. Keeper", "Goalkeeper"), ("C. Back", "Defender"), ("W. Ing", "Forward")]
    assert all(p.team.provider_id == "57" and p.shirt_number is None for p in squad)
    # date of birth is in the payload but never makes it into our normalized model
    assert "dateOfBirth" not in squad[0].model_dump() and "date_of_birth" not in squad[0].model_dump()

    player = await provider.get_player("2")
    assert player.position == "Defender" and player.team.name == "Arsenal FC"
    assert await provider.get_player("404") is None
    assert await provider.get_team_squad("404") == []
