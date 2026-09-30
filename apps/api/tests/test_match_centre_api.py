"""Phase 4 match-centre API: timeline, lineups, statistics, form,
head-to-head, capabilities. Uses `phase4_client` (seeded + per-match extras
stored, as the worker's live loop would)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.redis_keys import RedisKeys
from app.models.enums import MatchEventType
from app.models.match_event import MatchEvent
from app.models.player import Player

# -- capabilities -----------------------------------------------------------------


async def test_capabilities_reports_mock_provider_support(client):
    resp = await client.get("/api/v1/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["lineups"] is True
    assert data["match_statistics"] is True
    assert data["top_scorers"] is True
    # derived from stored results, not from the provider
    assert data["head_to_head"] is True and data["form"] is True


# -- match details / timeline ---------------------------------------------------------


async def test_finished_match_timeline_is_chronological_with_metadata(phase4_client, get_match_id):
    match_id = await get_match_id("epl-3")  # Man Utd 2-2 Aston Villa, finished
    detail = (await phase4_client.get(f"/api/v1/matches/{match_id}")).json()

    assert detail["status"] == "finished"
    assert (detail["home_score"], detail["away_score"]) == (2, 2)
    minutes = [e["minute"] for e in detail["events"]]
    assert minutes == sorted(minutes) and minutes[0] == 14
    red = next(e for e in detail["events"] if e["event_type"] == "red_card")
    assert red["player"]["name"] == "Casemiro" and red["team"]["short_name"] == "MUN"
    penalty = next(e for e in detail["events"] if e["event_type"] == "penalty")
    assert penalty["description"] == "Penalty"


async def test_timeline_orders_added_time_after_the_regular_minute(phase4_client, get_match_id, test_engine):
    """45' then 45+2' then 46': a NULL extra_minute must sort as 0, not last."""
    match_id = await get_match_id("epl-3")
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        for key, minute, extra in (("x-1", 45, 2), ("x-2", 45, None), ("x-3", 46, None)):
            session.add(
                MatchEvent(
                    match_id=match_id,
                    provider_id=key,
                    event_type=MatchEventType.YELLOW_CARD,
                    minute=minute,
                    extra_minute=extra,
                )
            )
        await session.commit()

    events = (await phase4_client.get(f"/api/v1/matches/{match_id}/events")).json()
    around_half = [(e["minute"], e["extra_minute"]) for e in events if e["minute"] in (45, 46)]
    assert around_half == [(45, None), (45, 2), (46, None)]


async def test_event_detail_is_exposed(phase4_client, get_match_id, test_engine):
    match_id = await get_match_id("epl-3")
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        session.add(
            MatchEvent(
                match_id=match_id,
                provider_id="var-1",
                event_type=MatchEventType.VAR,
                minute=33,
                event_detail="Goal disallowed",
            )
        )
        await session.commit()
    events = (await phase4_client.get(f"/api/v1/matches/{match_id}/events")).json()
    var = next(e for e in events if e["event_type"] == "var")
    assert var["event_detail"] == "Goal disallowed"


# -- lineups ----------------------------------------------------------------------------


async def test_lineups_have_starting_xi_substitutes_and_formation(phase4_client, get_match_id):
    match_id = await get_match_id("epl-3")
    lineups = (await phase4_client.get(f"/api/v1/matches/{match_id}/lineups")).json()

    for side, team_short in (("home", "MUN"), ("away", "AVL")):
        lineup = lineups[side]
        assert lineup["team"]["short_name"] == team_short
        assert lineup["formation"] == "4-3-3"
        assert len(lineup["starters"]) == 11
        assert len(lineup["substitutes"]) == 7
        goalkeepers = [p for p in lineup["starters"] if p["position"] == "Goalkeeper"]
        assert len(goalkeepers) == 1 and lineup["starters"][0] is not None
        assert all(p["shirt_number"] is not None for p in lineup["starters"] + lineup["substitutes"])
    # every scorer in the timeline started the match
    scorers = {"Watkins", "Fernandes", "Højlund", "Rogers"}
    starters = {p["player"]["name"] for side in ("home", "away") for p in lineups[side]["starters"]}
    assert scorers <= starters


async def test_lineup_substitutions_are_connected_to_substitution_events(
    phase4_client, get_match_id, test_engine, fake_redis
):
    match_id = await get_match_id("epl-3")
    lineups = (await phase4_client.get(f"/api/v1/matches/{match_id}/lineups")).json()
    starter = lineups["home"]["starters"][3]["player"]["id"]
    sub = lineups["home"]["substitutes"][0]["player"]["id"]

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        session.add(
            MatchEvent(
                match_id=match_id,
                provider_id="sub-1",
                event_type=MatchEventType.SUBSTITUTION,
                minute=61,
                player_id=sub,  # coming on
                assist_player_id=starter,  # going off
            )
        )
        await session.commit()
    # (the worker drops this cache entry when it sees a SUBSTITUTION --
    # see test_e2e_match_centre.py; here the event is written directly.)
    await fake_redis.delete(RedisKeys.match_lineups(match_id))

    lineups = (await phase4_client.get(f"/api/v1/matches/{match_id}/lineups")).json()
    by_id = {p["player"]["id"]: p for p in lineups["home"]["starters"] + lineups["home"]["substitutes"]}
    assert by_id[starter]["subbed_out_minute"] == 61 and by_id[starter]["subbed_in_minute"] is None
    assert by_id[sub]["subbed_in_minute"] == 61 and by_id[sub]["subbed_out_minute"] is None


async def test_lineups_are_unavailable_not_an_error_for_an_upcoming_match(phase4_client, get_match_id):
    match_id = await get_match_id("epl-4")  # scheduled
    resp = await phase4_client.get(f"/api/v1/matches/{match_id}/lineups")
    assert resp.status_code == 200
    assert resp.json() == {"home": None, "away": None}


# -- statistics ----------------------------------------------------------------------------


async def test_match_statistics_for_a_finished_match(phase4_client, get_match_id):
    match_id = await get_match_id("epl-3")
    stats = (await phase4_client.get(f"/api/v1/matches/{match_id}/statistics")).json()
    home, away = stats["home"], stats["away"]

    assert home["possession"] + away["possession"] == 100
    assert home["shots"] >= 2 and away["shots"] >= 2  # at least the goals they scored
    assert home["shots_on_target"] <= home["shots"]
    assert home["red_cards"] == 1 and away["red_cards"] == 0  # from the timeline's red card
    # a statistic the provider didn't supply stays null -- never a fabricated 0
    assert home["expected_goals"] is None and away["expected_goals"] is None


async def test_match_statistics_empty_for_a_match_that_has_not_started(phase4_client, get_match_id):
    match_id = await get_match_id("epl-4")
    assert (await phase4_client.get(f"/api/v1/matches/{match_id}/statistics")).json() == {
        "home": None,
        "away": None,
    }


async def test_player_match_statistics(phase4_client, get_match_id):
    match_id = await get_match_id("epl-3")
    players = (await phase4_client.get(f"/api/v1/matches/{match_id}/players")).json()["players"]

    assert len(players) >= 22
    by_name = {p["player"]["name"]: p for p in players}
    assert by_name["Watkins"]["goals"] == 1
    assert by_name["Bailey"]["assists"] == 1
    assert by_name["Casemiro"]["red_cards"] == 1
    assert all(0 <= (p["minutes_played"] or 0) <= 90 for p in players)
    # home side first
    home_team = (await phase4_client.get(f"/api/v1/matches/{match_id}")).json()["home_team"]["id"]
    assert players[0]["team_id"] == home_team


async def test_unknown_match_returns_404_on_every_phase4_route(phase4_client):
    for suffix in ("lineups", "statistics", "players", "form", "head-to-head"):
        resp = await phase4_client.get(f"/api/v1/matches/999999/{suffix}")
        assert resp.status_code == 404, suffix


# -- form -------------------------------------------------------------------------------------


async def test_team_form_last_five_overall(phase4_client):
    liverpool = (await phase4_client.get("/api/v1/search?q=Liverpool")).json()["teams"][0]["id"]
    form = (await phase4_client.get(f"/api/v1/teams/{liverpool}/form")).json()

    assert form["scope"] == "overall" and form["limit"] == 5
    assert len(form["results"]) == 5
    assert len(form["sequence"]) == 5 and set(form["sequence"]) <= set("WDL")
    kickoffs = [r["kickoff_time"] for r in form["results"]]
    assert kickoffs == sorted(kickoffs, reverse=True)  # most recent first
    # sequence is the same results, oldest -> newest
    assert form["sequence"] == "".join(r["result"] for r in reversed(form["results"]))
    for r in form["results"]:
        expected = "W" if r["goals_for"] > r["goals_against"] else "D" if r["goals_for"] == r["goals_against"] else "L"
        assert r["result"] == expected


async def test_team_form_home_and_away_scopes_only_include_that_venue(phase4_client):
    liverpool = (await phase4_client.get("/api/v1/search?q=Liverpool")).json()["teams"][0]["id"]
    home = (await phase4_client.get(f"/api/v1/teams/{liverpool}/form?scope=home")).json()
    away = (await phase4_client.get(f"/api/v1/teams/{liverpool}/form?scope=away")).json()

    assert home["results"] and all(r["venue"] == "home" for r in home["results"])
    assert away["results"] and all(r["venue"] == "away" for r in away["results"])


async def test_team_form_rejects_unknown_scope_and_unknown_team(phase4_client):
    assert (await phase4_client.get("/api/v1/teams/1/form?scope=sideways")).status_code == 422
    assert (await phase4_client.get("/api/v1/teams/999999/form")).status_code == 404


async def test_team_with_no_stored_results_has_empty_form_not_an_error(phase4_client):
    brighton = (await phase4_client.get("/api/v1/search?q=Brighton")).json()["teams"][0]["id"]
    form = (await phase4_client.get(f"/api/v1/teams/{brighton}/form")).json()
    assert form["results"] == [] and form["sequence"] == ""


async def test_match_form_only_uses_results_before_kickoff(phase4_client, get_match_id):
    match_id = await get_match_id("epl-1")
    match = (await phase4_client.get(f"/api/v1/matches/{match_id}")).json()
    form = (await phase4_client.get(f"/api/v1/matches/{match_id}/form")).json()

    assert form["home"]["team_id"] == match["home_team"]["id"]
    assert form["home"]["results"] and form["away"]["results"]
    for side in ("home", "away"):
        assert all(r["kickoff_time"] < match["kickoff_time"] for r in form[side]["results"])
        assert all(r["match_id"] != match_id for r in form[side]["results"])


async def test_match_form_venue_scope(phase4_client, get_match_id):
    match_id = await get_match_id("epl-1")
    form = (await phase4_client.get(f"/api/v1/matches/{match_id}/form?scope=venue")).json()
    assert form["home"]["scope"] == "home" and all(r["venue"] == "home" for r in form["home"]["results"])
    assert form["away"]["scope"] == "away" and all(r["venue"] == "away" for r in form["away"]["results"])


# -- head to head -------------------------------------------------------------------------------


async def test_head_to_head_summary_and_explicit_period(phase4_client, get_match_id):
    match_id = await get_match_id("epl-1")  # Liverpool v Chelsea
    match = (await phase4_client.get(f"/api/v1/matches/{match_id}")).json()
    h2h = (await phase4_client.get(f"/api/v1/matches/{match_id}/head-to-head")).json()

    assert h2h["limit"] == 5
    assert len(h2h["meetings"]) == 2  # two generated past meetings
    assert h2h["home_team_wins"] + h2h["draws"] + h2h["away_team_wins"] == len(h2h["meetings"])
    assert h2h["before"] == match["kickoff_time"]
    assert h2h["period_start"] < h2h["before"]
    for meeting in h2h["meetings"]:
        assert meeting["kickoff_time"] < h2h["before"]
        assert {meeting["home_team"]["id"], meeting["away_team"]["id"]} == {
            match["home_team"]["id"],
            match["away_team"]["id"],
        }
    kickoffs = [m["kickoff_time"] for m in h2h["meetings"]]
    assert kickoffs == sorted(kickoffs, reverse=True)


async def test_head_to_head_counts_wins_relative_to_the_matchs_home_team(phase4_client, get_match_id):
    match_id = await get_match_id("epl-1")
    h2h = (await phase4_client.get(f"/api/v1/matches/{match_id}/head-to-head")).json()
    home_id = h2h["home_team_id"]

    expected = {"home": 0, "draw": 0, "away": 0}
    for m in h2h["meetings"]:
        if m["home_score"] == m["away_score"]:
            expected["draw"] += 1
            continue
        winner = m["home_team"]["id"] if m["home_score"] > m["away_score"] else m["away_team"]["id"]
        expected["home" if winner == home_id else "away"] += 1
    assert (h2h["home_team_wins"], h2h["draws"], h2h["away_team_wins"]) == (
        expected["home"],
        expected["draw"],
        expected["away"],
    )


async def test_head_to_head_with_no_history_is_empty_not_an_error(phase4_client, get_match_id):
    match_id = await get_match_id("epl-4")  # Brighton v West Ham: no generated history
    h2h = (await phase4_client.get(f"/api/v1/matches/{match_id}/head-to-head")).json()
    assert h2h["meetings"] == []
    assert (h2h["home_team_wins"], h2h["draws"], h2h["away_team_wins"]) == (0, 0, 0)


# -- caching ----------------------------------------------------------------------------------------


async def test_match_centre_reads_populate_redis_with_status_appropriate_ttls(
    phase4_client, get_match_id, fake_redis
):
    from app.core.config import settings
    from app.core.redis_keys import RedisKeys

    finished = await get_match_id("epl-3")
    live = await get_match_id("epl-1")
    for match_id in (finished, live):
        for suffix in ("lineups", "statistics"):
            assert (await phase4_client.get(f"/api/v1/matches/{match_id}/{suffix}")).status_code == 200

    client = fake_redis._client
    finished_ttl = await client.ttl(RedisKeys.match_lineups(finished))
    live_ttl = await client.ttl(RedisKeys.match_lineups(live))
    assert 0 < live_ttl <= settings.redis_live_match_ttl_seconds
    assert live_ttl < finished_ttl <= settings.redis_static_ttl_seconds
    assert await client.exists(RedisKeys.match_statistics(finished)) == 1


async def test_player_rows_are_not_duplicated_across_repeated_reads(phase4_client, get_match_id, test_engine):
    match_id = await get_match_id("epl-3")
    for _ in range(3):
        await phase4_client.get(f"/api/v1/matches/{match_id}/lineups")
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        names = (await session.execute(select(Player.provider_id))).scalars().all()
    assert len(names) == len(set(names))


# -- cache hits cost no database work ---------------------------------------------------------------


async def test_a_cache_hit_issues_no_database_queries(phase4_client, get_match_id, test_engine):
    """Validation/lookup of the match happens inside the cache loader, so a
    repeat read of cached match-centre data never touches PostgreSQL."""
    from sqlalchemy import event

    match_id = await get_match_id("epl-3")
    haaland = (await phase4_client.get("/api/v1/search?q=Haaland")).json()["players"][0]["id"]
    liverpool = (await phase4_client.get("/api/v1/search?q=Liverpool")).json()["teams"][0]["id"]
    paths = [
        f"/api/v1/matches/{match_id}/lineups",
        f"/api/v1/matches/{match_id}/statistics",
        f"/api/v1/matches/{match_id}/players",
        f"/api/v1/matches/{match_id}/form",
        f"/api/v1/matches/{match_id}/head-to-head",
        f"/api/v1/teams/{liverpool}",
        f"/api/v1/teams/{liverpool}/players",
        f"/api/v1/teams/{liverpool}/statistics",
        f"/api/v1/teams/{liverpool}/form",
        f"/api/v1/players/{haaland}",
        f"/api/v1/players/{haaland}/statistics",
    ]
    for path in paths:  # first pass: populate the cache
        assert (await phase4_client.get(path)).status_code == 200, path

    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", _count)
    try:
        for path in paths:
            assert (await phase4_client.get(path)).status_code == 200, path
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", _count)
    assert statements == [], statements[:3]


async def test_unknown_ids_are_still_404_when_the_cache_is_cold(phase4_client):
    for path in ("/api/v1/teams/999999/players", "/api/v1/players/999999", "/api/v1/matches/999999/form"):
        assert (await phase4_client.get(path)).status_code == 404, path


async def test_on_demand_sync_requests_respect_a_global_budget(fake_redis, monkeypatch):
    from app.core.config import settings
    from app.services.cache import CacheAside
    from app.services.sync_requests import request_sync_once

    monkeypatch.setattr(settings, "sync_request_budget_per_minute", 5)
    cache = CacheAside(fake_redis)
    queued: list[int] = []
    # walking many different ids (a scraper) must not flood the provider
    results = [
        await request_sync_once(cache, "player", player_id, lambda pid=player_id: queued.append(pid))
        for player_id in range(1, 26)
    ]
    assert results.count(True) == 5 and len(queued) == 5
    # the same id is debounced regardless of budget
    assert await request_sync_once(cache, "player", 1, lambda: queued.append(1)) is False
    # and with no cache (no Redis) nothing is ever enqueued
    assert await request_sync_once(None, "player", 99, lambda: queued.append(99)) is False
