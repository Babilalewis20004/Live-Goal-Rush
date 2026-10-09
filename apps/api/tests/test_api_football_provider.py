"""ApiFootballProvider against recorded API-Football v3 responses
(tests/fixtures/api_football/*.json -- real payloads, trimmed). No network:
an `httpx.MockTransport` serves them and records every request."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.services.providers.api_football_provider import (
    QUOTA_RESERVE,
    ApiFootballProvider,
    parse_league_ids,
)
from app.services.providers.base import ProviderQuotaExhausted
from app.worker.provider_guard import ProviderUnavailableError, call_with_backoff

FIXTURES = Path(__file__).parent / "fixtures" / "api_football"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def envelope(response: list[dict]) -> dict:
    return {"get": "x", "parameters": {}, "errors": [], "results": len(response), "response": response}


class FakeApi:
    """Routes requests by path to canned payloads and records them."""

    def __init__(self, routes: dict[str, object], remaining: int | None = 5000) -> None:
        self.routes = routes
        self.remaining = remaining
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = self.routes[request.url.path]
        if callable(payload):
            payload = payload(request)
        headers = {} if self.remaining is None else {"x-ratelimit-requests-remaining": str(self.remaining)}
        return httpx.Response(200, json=payload, headers=headers)

    def count(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path == path)


def make_provider(api: FakeApi, league_ids: str = "39") -> ApiFootballProvider:
    provider = ApiFootballProvider(api_key="test-key", league_ids=league_ids)
    provider._client = httpx.AsyncClient(
        base_url="https://v3.football.api-sports.io", transport=httpx.MockTransport(api)
    )
    return provider


def routes_for_competition() -> dict[str, object]:
    return {
        "/leagues": load("league.json"),
        "/standings": load("standings.json"),
        "/players/topscorers": load("topscorers.json"),
        "/fixtures": load("fixture_detail.json"),
        "/fixtures/lineups": load("lineups.json"),
        "/fixtures/statistics": load("statistics.json"),
        "/fixtures/players": load("players.json"),
        "/players/squads": load("squad.json"),
    }


# -- mapping ----------------------------------------------------------------


async def test_finished_match_mapping():
    provider = make_provider(FakeApi(routes_for_competition()))
    match = await provider.get_match("1557367")

    assert match is not None
    assert (match.home_team.name, match.away_team.name) == ("Arsenal", "Coventry")
    assert (match.home_score, match.away_score) == (3, 0)
    assert (match.half_time_home_score, match.half_time_away_score) == (2, 0)
    assert match.status == "finished"
    assert match.minute is None  # only in-play matches carry a minute
    assert match.competition.provider_id == "39"
    assert match.competition.type == "league"


async def test_events_are_normalised_sorted_and_unique():
    provider = make_provider(FakeApi(routes_for_competition()))
    match = await provider.get_match("1557367")

    assert match is not None
    events = match.events
    assert len(events) == 14
    assert [e.minute for e in events] == sorted(e.minute for e in events)
    assert len({e.provider_id for e in events}) == len(events)
    assert {e.event_type for e in events} <= {
        "goal", "own_goal", "penalty", "yellow_card", "red_card", "second_yellow", "substitution",
    }
    assert sum(e.event_type == "goal" for e in events) == 3


async def test_substitution_player_is_the_one_coming_on():
    provider = make_provider(FakeApi(routes_for_competition()))
    match = await provider.get_match("1557367")

    first_sub = next(e for e in match.events if e.event_type == "substitution")
    # API-Football: player = going off, assist = coming on. The app's
    # convention (MatchEventOut) is the reverse.
    assert first_sub.player.name == "V. Torp"
    assert first_sub.assist_player.name == "C. Yirenkyi"


@pytest.mark.parametrize(
    ("short", "expected"),
    [("NS", "scheduled"), ("1H", "live"), ("2H", "live"), ("HT", "halftime"), ("FT", "finished"),
     ("AET", "finished"), ("PEN", "finished"), ("PST", "postponed"), ("CANC", "cancelled"), ("???", "scheduled")],
)
async def test_status_mapping(short, expected):
    raw = load("fixture_detail.json")
    raw["response"][0]["fixture"]["status"] = {"short": short, "elapsed": 63, "extra": None}
    provider = make_provider(FakeApi({"/fixtures": raw}))
    match = await provider.get_match("1557367")

    assert match.status == expected
    assert (match.minute == 63) == (expected == "live")


async def test_var_and_missed_penalty_events_are_dropped():
    raw = load("fixture_detail.json")
    events = raw["response"][0]["events"]
    base = events[0]
    events.append({**base, "type": "Var", "detail": "Goal cancelled"})
    events.append({**base, "type": "Goal", "detail": "Missed Penalty"})
    provider = make_provider(FakeApi({"/fixtures": raw}))
    match = await provider.get_match("1557367")

    assert len(match.events) == 14


async def test_standings_mapping():
    provider = make_provider(FakeApi(routes_for_competition()))
    rows = await provider.get_standings("39")

    first = rows[0]
    assert (first.position, first.team.name, first.points) == (1, "Manchester City", 15)
    assert first.form == "WWWWW"
    assert first.season == "2026/27"
    assert first.description.startswith("Promotion")
    assert first.group is None  # a single table is not a group stage
    assert [r.position for r in rows] == sorted(r.position for r in rows)


async def test_historical_standings_use_the_requested_season_year():
    api = FakeApi(routes_for_competition())
    provider = make_provider(api)
    await provider.get_historical_standings("39", "2024/25")

    standings = [r for r in api.requests if r.url.path == "/standings"]
    assert standings[0].url.params["season"] == "2024"


async def test_top_scorers_mapping():
    provider = make_provider(FakeApi(routes_for_competition()))
    scorers = await provider.get_top_scorers("39")

    assert scorers[0].player.name == "E. Haaland"
    assert scorers[0].goals == 5
    assert scorers[0].season == "2026/27"
    assert scorers[0].team is not None


async def test_lineups_mapping():
    provider = make_provider(FakeApi(routes_for_competition()))
    lineups = await provider.get_lineups("1557367")

    home = lineups[0]
    assert home.formation == "4-2-3-1"
    assert sum(p.is_starter for p in home.players) == 11
    assert sum(not p.is_starter for p in home.players) == 9
    assert {p.position for p in home.players} <= {"Goalkeeper", "Defender", "Midfielder", "Forward"}


async def test_match_statistics_mapping():
    provider = make_provider(FakeApi(routes_for_competition()))
    stats = (await provider.get_match_statistics("1557367"))[0]

    assert stats.shots == 20
    assert stats.shots_on_target == 6
    assert isinstance(stats.possession, float)


async def test_player_statistics_mapping():
    provider = make_provider(FakeApi(routes_for_competition()))
    rows = await provider.get_player_statistics("1557367")

    assert rows
    assert all(r.team is not None and r.player.provider_id for r in rows)


async def test_squad_positions_are_normalised():
    provider = make_provider(FakeApi(routes_for_competition()))
    squad = await provider.get_team_squad("50")

    assert squad
    assert {p.position for p in squad} <= {"Goalkeeper", "Defender", "Midfielder", "Forward"}


# -- scope, enrichment ---------------------------------------------------------


async def test_fixtures_are_filtered_to_tracked_leagues_and_enriched_with_events():
    detail = load("fixture_detail.json")["response"][0]

    def no_events(fixture_id: int, league_id: int, short: str) -> dict:
        row = copy.deepcopy(detail)
        row.pop("events")
        row["fixture"]["id"] = fixture_id
        row["fixture"]["status"]["short"] = short
        row["league"]["id"] = league_id
        return row

    listing = envelope([
        no_events(1557367, 39, "FT"),   # tracked, finished -> enriched
        no_events(2, 39, "NS"),         # tracked, not started -> nothing to enrich
        no_events(3, 999, "FT"),        # other league -> dropped
    ])

    def fixtures(request: httpx.Request):
        return load("fixture_detail.json") if "ids" in request.url.params else listing

    api = FakeApi({"/fixtures": fixtures})
    provider = make_provider(api)
    matches = await provider.get_fixtures(date.today())

    assert [m.provider_id for m in matches] == ["1557367", "2"]
    assert len(matches[0].events) == 14
    assert matches[1].events == []
    id_calls = [r for r in api.requests if "ids" in r.url.params]
    assert len(id_calls) == 1
    assert id_calls[0].url.params["ids"] == "1557367"  # only the started match


async def test_live_matches_are_filtered_to_tracked_leagues():
    row = load("fixture_detail.json")["response"][0]
    other = copy.deepcopy(row)
    other["league"]["id"] = 999
    provider = make_provider(FakeApi({"/fixtures": envelope([row, other])}))

    assert [m.provider_id for m in await provider.get_live_matches()] == ["1557367"]


# -- caching & quota -----------------------------------------------------------------


async def test_repeated_reads_are_served_from_cache():
    api = FakeApi(routes_for_competition())
    provider = make_provider(api)

    await provider.get_standings("39")
    await provider.get_standings("39")
    await provider.get_top_scorers("39")
    await provider.get_top_scorers("39")

    assert api.count("/standings") == 1
    assert api.count("/players/topscorers") == 1
    assert api.count("/leagues") == 1  # season lookup shared by both


async def test_live_scores_are_never_cached():
    api = FakeApi({"/fixtures": envelope([])})
    provider = make_provider(api)

    await provider.get_live_matches()
    await provider.get_live_matches()

    assert api.count("/fixtures") == 2


async def test_quota_reserve_blocks_background_calls_but_not_live_scores():
    api = FakeApi({**routes_for_competition(), "/fixtures": envelope([])}, remaining=QUOTA_RESERVE - 1)
    provider = make_provider(api)

    await provider.get_live_matches()  # essential: learns the remaining quota
    assert provider.requests_remaining == QUOTA_RESERVE - 1

    with pytest.raises(ProviderQuotaExhausted):
        await provider.get_top_scorers("39")
    assert api.count("/players/topscorers") == 0  # refused before spending a request

    assert await provider.get_match("1") is None  # essential single-match detail still works


async def test_quota_exhaustion_is_not_retried():
    api = FakeApi({**routes_for_competition(), "/fixtures": envelope([])}, remaining=10)
    provider = make_provider(api)
    await provider.get_live_matches()

    attempts = 0

    async def op():
        nonlocal attempts
        attempts += 1
        return await provider.get_standings("39")

    with pytest.raises(ProviderUnavailableError):
        await call_with_backoff("standings", op)
    assert attempts == 1


async def test_api_errors_in_a_200_response_raise():
    body = {**envelope([]), "errors": {"requests": "You have reached the request limit for the day"}}
    provider = make_provider(FakeApi({"/fixtures": body}))

    with pytest.raises(RuntimeError, match="request limit"):
        await provider.get_live_matches()


async def test_get_player_prefers_the_club_over_a_national_team():
    def entry(team_id: int, name: str, league_id: int, appearances: int) -> dict:
        return {
            "team": {"id": team_id, "name": name, "logo": None},
            "league": {"id": league_id},
            "games": {"appearences": appearances, "position": "Goalkeeper"},
        }

    payload = envelope([{
        "player": {"id": 7, "name": "C. Brady", "photo": None, "nationality": "USA"},
        "statistics": [entry(2384, "USA", 10, 12), entry(1607, "Chicago Fire", 253, 30)],
    }])
    provider = make_provider(FakeApi({"/players": payload}), league_ids="253")
    assert (await provider.get_player("7")).team.name == "Chicago Fire"

    # no tracked-league entry: fall back to the most appearances
    provider = make_provider(FakeApi({"/players": payload}), league_ids="39")
    assert (await provider.get_player("7")).team.name == "Chicago Fire"

    # a national team with more appearances than the club still loses when the club is tracked
    payload["response"][0]["statistics"][0]["games"]["appearences"] = 99
    provider = make_provider(FakeApi({"/players": payload}), league_ids="253")
    assert (await provider.get_player("7")).team.name == "Chicago Fire"


async def test_injuries_keep_only_recent_absences_one_row_per_player():
    now = datetime.now(timezone.utc)

    def row(player_id: int, name: str, kind: str, days: int) -> dict:
        return {
            "player": {"id": player_id, "name": name, "photo": None, "type": kind, "reason": "Calf Injury"},
            "team": {"id": 50, "name": "Manchester City", "logo": None},
            "fixture": {"id": days, "date": (now + timedelta(days=days)).isoformat()},
            "league": {"id": 39},
        }

    payload = envelope([
        row(1, "Old Absence", "Missing Fixture", -30),   # history: has since returned
        row(2, "J. Doku", "Missing Fixture", -20),
        row(2, "J. Doku", "Missing Fixture", 2),        # same player, newer fixture wins
        row(3, "N. O'Reilly", "Questionable", 5),
    ])
    provider = make_provider(FakeApi({"/injuries": payload}))
    injuries = await provider.get_team_injuries("50")

    assert [i.player.name for i in injuries] == ["N. O'Reilly", "J. Doku"]  # newest fixture first
    assert [i.kind for i in injuries] == ["doubtful", "missing"]
    assert injuries[1].reason == "Calf Injury"


# -- misc ----------------------------------------------------------------------------


async def test_short_search_makes_no_request():
    api = FakeApi({})
    provider = make_provider(api)

    result = await provider.search("ar")

    assert (result.teams, result.competitions, result.players) == ([], [], [])
    assert api.requests == []


def test_parse_league_ids():
    assert parse_league_ids("39, 140 ,135") == ["39", "140", "135"]
    assert parse_league_ids("39,abc,,") == ["39"]
    assert parse_league_ids(None) == []


def test_missing_api_key_is_rejected():
    with pytest.raises(RuntimeError, match="FOOTBALL_API_KEY"):
        ApiFootballProvider(api_key="")
