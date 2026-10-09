"""Tests for the mock provider in isolation -- no DB, no HTTP, no app."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.fakes.mock_provider import MockFootballDataProvider

ALL_COMPETITION_IDS = {
    "comp-ucl",
    "comp-epl",
    "comp-laliga",
    "comp-seriea",
    "comp-bundesliga",
    "comp-ligue1",
}


@pytest.fixture
def provider() -> MockFootballDataProvider:
    return MockFootballDataProvider()


async def test_live_matches_only_returns_in_progress(provider):
    matches = await provider.get_live_matches()
    assert matches
    assert all(m.status in ("live", "halftime") for m in matches)


async def test_fixtures_are_filtered_by_date(provider):
    today = datetime.now(timezone.utc).date()
    matches = await provider.get_fixtures(today)
    assert matches
    assert all(m.kickoff_time.date() == today for m in matches)

    far_future = today + timedelta(days=365)
    assert await provider.get_fixtures(far_future) == []


async def test_get_match_by_provider_id(provider):
    match = await provider.get_match("ucl-1")
    assert match is not None
    assert match.home_team.provider_id == "t-rma"
    assert match.away_team.provider_id == "t-mci"

    assert await provider.get_match("does-not-exist") is None


async def test_finished_match_events_are_fully_revealed(provider):
    # epl-3 is "finished_today" -- unlike a "live"/"halftime" fixture, its
    # events aren't time-evolving (see mock_provider.py's module docstring),
    # so asserting its full event list is deterministic regardless of when
    # this test happens to run.
    match = await provider.get_match("epl-3")
    assert match is not None
    assert match.status == "finished"
    assert len(match.events) == 5


async def test_get_competitions_returns_all_of_them(provider):
    competitions = await provider.get_competitions()
    assert {c.provider_id for c in competitions} == ALL_COMPETITION_IDS


async def test_competition_fixtures_are_scoped_to_that_competition(provider):
    fixtures = await provider.get_competition_fixtures("comp-epl")
    assert fixtures
    assert all(m.competition.provider_id == "comp-epl" for m in fixtures)


async def test_standings_are_ranked_by_points_descending(provider):
    standings = await provider.get_standings("comp-epl")
    points = [row.points for row in standings]
    assert points == sorted(points, reverse=True)
    assert [row.position for row in standings] == list(range(1, len(standings) + 1))


async def test_get_team_known_and_unknown(provider):
    team = await provider.get_team("t-rma")
    assert team is not None
    assert team.name == "Real Madrid"
    assert await provider.get_team("does-not-exist") is None


async def test_team_fixtures_include_both_home_and_away_matches(provider):
    fixtures = await provider.get_team_fixtures("t-mci")
    assert fixtures
    assert all("t-mci" in (m.home_team.provider_id, m.away_team.provider_id) for m in fixtures)


async def test_search_matches_teams_competitions_and_players(provider):
    assert any(t.name == "Arsenal" for t in (await provider.search("Arsenal")).teams)
    assert any(c.name == "Premier League" for c in (await provider.search("Premier")).competitions)
    assert any(p.name == "Haaland" for p in (await provider.search("Haaland")).players)


async def test_search_empty_query_returns_empty_result(provider):
    results = await provider.search("   ")
    assert results.teams == []
    assert results.competitions == []
    assert results.players == []
