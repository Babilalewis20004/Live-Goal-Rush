"""Phase 4: team pages (detail, squad, statistics), player pages, competition
pages (fixtures/results scopes, standings seasons/groups, top scorers) and
database-backed search."""

from sqlalchemy import select

from app.core.redis_keys import RedisKeys
from app.models.competition import Competition
from app.models.standing import Standing
from app.models.team import Team
from app.services.football_service import FootballService
from tests.fakes.mock_provider import MockFootballDataProvider
from app.services.season import current_season_label
from app.services.team_player_service import TeamPlayerService


async def _team_id(client, name: str) -> int:
    return (await client.get(f"/api/v1/search?q={name}")).json()["teams"][0]["id"]


async def _competition_id(client, name: str) -> int:
    return (await client.get(f"/api/v1/search?q={name}")).json()["competitions"][0]["id"]


# -- team detail -------------------------------------------------------------------------


async def test_team_detail_has_venue_and_competitions(seeded_client):
    liverpool = await _team_id(seeded_client, "Liverpool")
    team = (await seeded_client.get(f"/api/v1/teams/{liverpool}")).json()

    assert team["name"] == "Liverpool" and team["venue"] == "Anfield"
    assert [c["name"] for c in team["competitions"]] == ["Premier League"]


async def test_team_in_two_competitions_lists_both(seeded_client):
    real_madrid = await _team_id(seeded_client, "Real Madrid")
    team = (await seeded_client.get(f"/api/v1/teams/{real_madrid}")).json()
    assert sorted(c["name"] for c in team["competitions"]) == ["Champions League", "LaLiga"]


async def test_team_results_are_most_recent_first_and_fixtures_soonest_first(seeded_client):
    liverpool = await _team_id(seeded_client, "Liverpool")
    results = (await seeded_client.get(f"/api/v1/teams/{liverpool}/results?page_size=100")).json()["items"]
    kickoffs = [m["kickoff_time"] for m in results]
    assert len(results) > 5 and kickoffs == sorted(kickoffs, reverse=True)
    assert all(m["status"] == "finished" for m in results)


# -- squad ---------------------------------------------------------------------------------


async def test_squad_is_empty_until_synced_then_sorted_by_position_and_number(seeded_client, session_factory):
    liverpool = await _team_id(seeded_client, "Liverpool")

    async with session_factory() as session:
        team = (await session.execute(select(Team).where(Team.id == liverpool))).scalar_one()
        provider = MockFootballDataProvider()
        assert await TeamPlayerService(session, provider).sync_squad(team) == 18
        await session.commit()

    squad = (await seeded_client.get(f"/api/v1/teams/{liverpool}/players")).json()
    assert len(squad) == 18
    positions = [p["position"] for p in squad]
    order = {"Goalkeeper": 0, "Defender": 1, "Midfielder": 2, "Forward": 3}
    assert [order[p] for p in positions] == sorted(order[p] for p in positions)
    goalkeepers = [p for p in squad if p["position"] == "Goalkeeper"]
    assert [p["shirt_number"] for p in goalkeepers] == [1, 13]
    assert {"Salah", "Gakpo"} <= {p["name"] for p in squad}


async def test_squad_sync_is_idempotent_and_detaches_players_who_left(
    seeded_client, session_factory, fake_redis
):
    liverpool = await _team_id(seeded_client, "Liverpool")

    class _SmallerSquad(MockFootballDataProvider):
        async def get_team_squad(self, team_id):
            return (await super().get_team_squad(team_id))[:10]

    async with session_factory() as session:
        team = (await session.execute(select(Team).where(Team.id == liverpool))).scalar_one()
        service = TeamPlayerService(session, MockFootballDataProvider())
        await service.sync_squad(team)
        await service.sync_squad(team)  # again: no duplicates
        await session.commit()
    await fake_redis.delete(RedisKeys.team_squad(liverpool))
    assert len((await seeded_client.get(f"/api/v1/teams/{liverpool}/players")).json()) == 18

    async with session_factory() as session:
        team = (await session.execute(select(Team).where(Team.id == liverpool))).scalar_one()
        await TeamPlayerService(session, _SmallerSquad()).sync_squad(team)
        await session.commit()
    await fake_redis.delete(RedisKeys.team_squad(liverpool))  # what the worker does after a squad sync
    assert len((await seeded_client.get(f"/api/v1/teams/{liverpool}/players")).json()) == 10


async def test_empty_provider_squad_never_detaches_an_existing_squad(seeded_client, session_factory):
    liverpool = await _team_id(seeded_client, "Liverpool")

    class _NoSquad(MockFootballDataProvider):
        async def get_team_squad(self, team_id):
            return []

    async with session_factory() as session:
        team = (await session.execute(select(Team).where(Team.id == liverpool))).scalar_one()
        await TeamPlayerService(session, MockFootballDataProvider()).sync_squad(team)
        assert await TeamPlayerService(session, _NoSquad()).sync_squad(team) == 0
        await session.commit()
    assert len((await seeded_client.get(f"/api/v1/teams/{liverpool}/players")).json()) == 18


async def test_squad_read_requests_a_background_sync_once(seeded_client, fake_redis, monkeypatch):
    from app.worker import tasks

    calls: list[str] = []
    monkeypatch.setattr(tasks.sync_team, "delay", lambda provider_id: calls.append(provider_id))

    liverpool = await _team_id(seeded_client, "Liverpool")
    for _ in range(3):
        assert (await seeded_client.get(f"/api/v1/teams/{liverpool}/players")).status_code == 200
    assert calls == ["t-liv"]  # debounced: one request, not one per read


async def test_unknown_team_routes_404(seeded_client):
    for suffix in ("players", "statistics"):
        assert (await seeded_client.get(f"/api/v1/teams/999999/{suffix}")).status_code == 404


# -- team statistics -------------------------------------------------------------------------


async def test_team_statistics_are_scoped_to_competition_and_season(seeded_client):
    real_madrid = await _team_id(seeded_client, "Real Madrid")
    stats = (await seeded_client.get(f"/api/v1/teams/{real_madrid}/statistics")).json()["seasons"]

    assert sorted(s["competition_name"] for s in stats) == ["Champions League", "LaLiga"]
    for row in stats:
        assert row["season"] == current_season_label()
        assert row["played"] == row["won"] + row["drawn"] + row["lost"]
        assert row["goal_difference"] == row["goals_for"] - row["goals_against"]
        assert row["points"] == row["won"] * 3 + row["drawn"]
        assert row["group"] == ""


# -- players -------------------------------------------------------------------------------------


async def test_player_profile_and_statistics(phase4_client, session_factory):
    haaland = (await phase4_client.get("/api/v1/search?q=Haaland")).json()["players"][0]
    profile = (await phase4_client.get(f"/api/v1/players/{haaland['id']}")).json()
    assert profile["name"] == "Haaland" and profile["position"] == "Forward"
    assert profile["team"]["name"] == "Manchester City"  # from the top-scorer sync

    stats = (await phase4_client.get(f"/api/v1/players/{haaland['id']}/statistics")).json()
    assert stats["seasons"]
    season = stats["seasons"][0]
    assert season["season"] == current_season_label() and season["goals"] > 0
    assert season["competition_name"] in {"Premier League", "Champions League"}


async def test_player_recent_matches_come_from_stored_match_statistics(phase4_client):
    watkins = (await phase4_client.get("/api/v1/search?q=Watkins")).json()["players"][0]
    stats = (await phase4_client.get(f"/api/v1/players/{watkins['id']}/statistics")).json()
    assert len(stats["recent_matches"]) == 1
    appearance = stats["recent_matches"][0]
    assert appearance["stats"]["goals"] == 1
    assert appearance["match"]["home_team"]["name"] == "Manchester United"


async def test_unknown_player_404(seeded_client):
    assert (await seeded_client.get("/api/v1/players/999999")).status_code == 404
    assert (await seeded_client.get("/api/v1/players/999999/statistics")).status_code == 404


async def test_player_profile_sync_enriches_a_stub_player(seeded_client, session_factory, fake_redis):
    from app.models.player import Player
    from app.services.providers.schemas import ProviderPlayer

    # A stub exactly as a match event or search hit would create it: a name
    # and nothing else.
    async with session_factory() as session:
        stub = await FootballService(db=session, provider=MockFootballDataProvider())._sync_player(
            ProviderPlayer(provider_id="p-navas", name="Navas"), None
        )
        await session.commit()
        player_id = stub.id
        assert stub.profile_synced_at is None and stub.shirt_number is None

    before = (await seeded_client.get(f"/api/v1/players/{player_id}")).json()
    assert before["shirt_number"] is None and before["nationality"] is None

    async with session_factory() as session:
        await TeamPlayerService(session, MockFootballDataProvider()).sync_player("p-navas")
        await session.commit()
        row = (await session.execute(select(Player).where(Player.id == player_id))).scalar_one()
        assert row.profile_synced_at is not None

    await fake_redis.delete(RedisKeys.player(player_id))  # the worker's post-sync invalidation
    profile = (await seeded_client.get(f"/api/v1/players/{player_id}")).json()
    assert profile["shirt_number"] is not None
    assert profile["team"]["name"] == "Sevilla"
    assert profile["position"] == "Defender"


async def test_thin_payloads_never_wipe_enriched_player_or_team_fields(seeded_client, session_factory):
    from app.models.player import Player
    from app.services.providers.schemas import ProviderPlayer, ProviderTeam

    async with session_factory() as session:
        service = FootballService(db=session, provider=MockFootballDataProvider())
        await TeamPlayerService(session, MockFootballDataProvider(), service).sync_player("p-salah")
        # the same player again, as a bare match-event participant / search hit
        await service._sync_player(ProviderPlayer(provider_id="p-salah", name="Salah"), None)
        # and a team as embedded in a match payload (no venue)
        await service._sync_team(ProviderTeam(provider_id="t-liv", name="Liverpool"))
        await session.commit()

        salah = (await session.execute(select(Player).where(Player.provider_id == "p-salah"))).scalar_one()
        assert salah.shirt_number is not None and salah.team_id is not None and salah.position == "Forward"
        liverpool = (await session.execute(select(Team).where(Team.provider_id == "t-liv"))).scalar_one()
        assert liverpool.venue == "Anfield"


# -- competitions -------------------------------------------------------------------------------------


async def test_competition_fixtures_scopes(seeded_client):
    epl = await _competition_id(seeded_client, "Premier")
    upcoming = (await seeded_client.get(f"/api/v1/competitions/{epl}/fixtures?scope=upcoming")).json()
    results = (await seeded_client.get(f"/api/v1/competitions/{epl}/fixtures?scope=results&page_size=100")).json()

    assert upcoming["items"] and all(m["status"] in ("scheduled", "live", "halftime") for m in upcoming["items"])
    up_kickoffs = [m["kickoff_time"] for m in upcoming["items"]]
    assert up_kickoffs == sorted(up_kickoffs)
    assert results["items"] and all(m["status"] == "finished" for m in results["items"])
    res_kickoffs = [m["kickoff_time"] for m in results["items"]]
    assert res_kickoffs == sorted(res_kickoffs, reverse=True)
    assert (await seeded_client.get(f"/api/v1/competitions/{epl}/fixtures?scope=bogus")).status_code == 422


async def test_standings_carry_season_zone_form_and_goal_difference(seeded_client):
    epl = await _competition_id(seeded_client, "Premier")
    rows = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings")).json()

    assert [r["position"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(r["season"] == current_season_label() for r in rows)
    assert rows[0]["description"] == "Champions League" and rows[-1]["description"] == "Relegation"
    assert rows[5]["description"] is None  # mid-table: no classification, not an invented one
    assert all(len(r["form"]) == 5 and set(r["form"]) <= set("WDL") for r in rows)
    assert all(r["goal_difference"] == r["goals_for"] - r["goals_against"] for r in rows)


async def test_standings_season_and_group_filtering(seeded_client, session_factory):
    epl = await _competition_id(seeded_client, "Premier")
    async with session_factory() as session:
        competition = (await session.execute(select(Competition).where(Competition.id == epl))).scalar_one()
        team = (await session.execute(select(Team).where(Team.name == "Liverpool"))).scalar_one()
        other = (await session.execute(select(Team).where(Team.name == "Arsenal"))).scalar_one()
        for team_row, group, pos in ((team, "Group A", 1), (other, "Group B", 1)):
            session.add(
                Standing(
                    competition_id=competition.id,
                    season="2024/25",
                    group_name=group,
                    team_id=team_row.id,
                    position=pos,
                    played=6, won=4, drawn=1, lost=1, goals_for=10, goals_against=4, points=13,
                )
            )
        await session.commit()

    current = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings")).json()
    assert {r["season"] for r in current} == {current_season_label()}  # latest season by default

    old = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings?season=2024/25")).json()
    assert {(r["group_name"], r["team"]["name"]) for r in old} == {("Group A", "Liverpool"), ("Group B", "Arsenal")}

    group_b = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings?season=2024/25&group=Group B")).json()
    assert [r["team"]["name"] for r in group_b] == ["Arsenal"]

    assert (await seeded_client.get(f"/api/v1/competitions/{epl}/standings?season=1999/00")).json() == []


async def test_standings_sync_is_idempotent_and_updates_in_place(seeded_client, session_factory):
    epl = await _competition_id(seeded_client, "Premier")

    class _ChangedTable(MockFootballDataProvider):
        async def get_standings(self, competition_id):
            rows = await super().get_standings(competition_id)
            rows[0].points += 3
            rows[0].played += 1
            return rows

    async def _count():
        async with session_factory() as session:
            return len((await session.execute(select(Standing).where(Standing.competition_id == epl))).scalars().all())

    before = await _count()
    async with session_factory() as session:
        competition = (await session.execute(select(Competition).where(Competition.id == epl))).scalar_one()
        service = FootballService(db=session, provider=_ChangedTable())
        await service.sync_standings(competition)
        await service.sync_standings(competition)
        await session.commit()
    assert await _count() == before  # upserted, never duplicated

    rows = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings")).json()
    assert rows[0]["points"] == 22  # 6 wins * 3 + 1 draw = 19, +3 from the changed provider table


async def test_unknown_competition_routes_404(seeded_client):
    assert (await seeded_client.get("/api/v1/competitions/999999/top-scorers")).status_code == 404


# -- top scorers -------------------------------------------------------------------------------------------


async def test_top_scorers_are_ranked_and_scoped_to_competition_and_season(seeded_client):
    epl = await _competition_id(seeded_client, "Premier")
    data = (await seeded_client.get(f"/api/v1/competitions/{epl}/top-scorers")).json()

    assert data["competition_id"] == epl and data["season"] == current_season_label()
    scorers = data["scorers"]
    assert scorers and [s["rank"] for s in scorers] == list(range(1, len(scorers) + 1))
    goals = [s["goals"] for s in scorers]
    assert goals == sorted(goals, reverse=True)
    assert all(s["team"] is not None and s["appearances"] for s in scorers)
    # only EPL players: the UCL table is computed separately
    assert {s["team"]["short_name"] for s in scorers} <= {"LIV", "MCI", "ARS", "CHE", "TOT", "NEW", "MUN", "AVL", "BHA", "WHU"}


async def test_top_scorers_empty_for_unknown_season_and_when_unsynced(seeded_client, client):
    epl = await _competition_id(seeded_client, "Premier")
    other_season = (await seeded_client.get(f"/api/v1/competitions/{epl}/top-scorers?season=1999/00")).json()
    assert other_season["scorers"] == []

    # A provider without the capability never stores any: the endpoint answers
    # with an empty list (and the capabilities endpoint says why).
    class _NoScorers(MockFootballDataProvider):
        @property
        def capabilities(self):
            return super().capabilities.model_copy(update={"top_scorers": False})

    assert _NoScorers().capabilities.top_scorers is False


# -- search ----------------------------------------------------------------------------------------------------


async def test_search_is_database_backed_and_includes_matches(seeded_client):
    data = (await seeded_client.get("/api/v1/search?q=Arsenal")).json()
    assert [t["name"] for t in data["teams"]] == ["Arsenal"]
    assert data["matches"], "matches involving the matched team"
    assert all("Arsenal" in (m["home_team"]["name"], m["away_team"]["name"]) for m in data["matches"])
    assert len(data["matches"]) <= 10  # bounded


async def test_search_players_and_competitions_partial_case_insensitive(seeded_client):
    data = (await seeded_client.get("/api/v1/search?q=prem")).json()
    assert [c["name"] for c in data["competitions"]] == ["Premier League"]
    data = (await seeded_client.get("/api/v1/search?q=ALAH")).json()
    assert [p["name"] for p in data["players"]] == ["Salah"]


async def test_search_treats_like_wildcards_literally(seeded_client):
    for q in ("%", "_", "a%"):
        data = (await seeded_client.get("/api/v1/search", params={"q": q})).json()
        assert data == {"teams": [], "competitions": [], "players": [], "matches": [], "articles": []}, q


async def test_search_matches_nearest_to_now_first(seeded_client):
    data = (await seeded_client.get("/api/v1/search?q=Liverpool")).json()
    kickoffs = [m["kickoff_time"] for m in data["matches"]]
    # the live match (kickoff ~ now) must come before months-old history
    assert data["matches"][0]["status"] in ("live", "halftime")
    assert len(kickoffs) > 1
