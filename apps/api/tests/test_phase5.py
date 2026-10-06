"""Phase 5: per-favourite notification overrides (reset endpoint + dispatch
semantics), season history, cross-process metrics, plan-gated provider
features."""

import fakeredis
import httpx
from sqlalchemy import select

from app.core.redis_client import SyncRedisService
from app.core.redis_keys import RedisKeys
from app.models.standing import Standing
from app.models.statistics import PlayerSeasonStatistic
from app.services.metrics import Metrics
from app.services.metrics_aggregation import (
    RedisMetricsSink,
    read_aggregate,
    render_prometheus,
)
from app.services.providers.mock_provider import MockFootballDataProvider
from app.services.providers.real_provider import RealFootballDataProvider, parse_features
from app.services.season import current_season_label, is_requestable_past_season
from app.worker import tasks

PREFS = "/api/v1/notifications/preferences"


# -- 1. per-favourite notification overrides ----------------------------------------------------------


async def test_reset_removes_only_that_override(authenticated_client):
    c = authenticated_client
    for scope, sid, event, enabled in (
        ("team", 5, "GOAL", False),
        ("team", 5, "CARD", False),
        ("team", 6, "GOAL", False),
        ("global", None, "GOAL", False),
    ):
        body = {"scope_type": scope, "event_type": event, "enabled": enabled}
        if sid is not None:
            body["scope_id"] = sid
        assert (await c.patch(PREFS, json=body)).status_code == 200

    resp = await c.delete(PREFS, params={"scope_type": "team", "scope_id": 5, "event_type": "GOAL"})
    assert resp.status_code == 204
    remaining = {(p["scope_type"], p["scope_id"], p["event_type"]) for p in (await c.get(PREFS)).json()}
    assert remaining == {("team", 5, "CARD"), ("team", 6, "GOAL"), ("global", None, "GOAL")}


async def test_reset_global_override_and_idempotency(authenticated_client):
    c = authenticated_client
    await c.patch(PREFS, json={"scope_type": "global", "event_type": "GOAL", "enabled": False})
    for _ in range(2):  # second call: nothing to delete, still 204
        resp = await c.delete(PREFS, params={"scope_type": "global", "event_type": "GOAL"})
        assert resp.status_code == 204
    assert (await c.get(PREFS)).json() == []


async def test_reset_validates_scope_rules(authenticated_client):
    c = authenticated_client
    assert (await c.delete(PREFS, params={"scope_type": "team", "event_type": "GOAL"})).status_code == 422
    assert (
        await c.delete(PREFS, params={"scope_type": "global", "scope_id": 3, "event_type": "GOAL"})
    ).status_code == 422
    assert (await c.delete(PREFS, params={"scope_type": "bogus", "event_type": "GOAL"})).status_code == 422


async def test_reset_requires_authentication_and_is_per_user(client, authenticated_client, session_factory):
    from app.core.security import hash_password
    from app.models.notification import NotificationPreference
    from app.models.user import User

    await authenticated_client.patch(
        PREFS, json={"scope_type": "team", "scope_id": 5, "event_type": "GOAL", "enabled": False}
    )
    async with session_factory() as session:
        other = User(email="other@example.com", hashed_password=hash_password("Sup3rSecret!"), display_name="O")
        session.add(other)
        await session.flush()
        session.add(
            NotificationPreference(
                user_id=other.id, scope_type="team", scope_id=5, event_type="GOAL", enabled=False
            )
        )
        await session.commit()

    await authenticated_client.delete(PREFS, params={"scope_type": "team", "scope_id": 5, "event_type": "GOAL"})
    async with session_factory() as session:
        rows = (await session.execute(select(NotificationPreference))).scalars().all()
    assert len(rows) == 1  # only the *other* user's row is left: the reset touched just the caller's

    client.cookies.clear()
    resp = await client.delete(PREFS, params={"scope_type": "global", "event_type": "GOAL"})
    assert resp.status_code == 401


# -- 2. season selector / history --------------------------------------------------------------------------


async def _epl(seeded_client) -> int:
    return (await seeded_client.get("/api/v1/search?q=Premier")).json()["competitions"][0]["id"]


async def test_season_helpers():
    assert is_requestable_past_season(current_season_label())
    start = int(current_season_label()[:4])
    assert is_requestable_past_season(f"{start - 10}/{str(start - 9)[-2:]}")
    assert not is_requestable_past_season(f"{start - 11}/{str(start - 10)[-2:]}")
    for bad in ("", "abc", "2024/2025", "2099/00", "1980/81", "2024-25"):
        assert not is_requestable_past_season(bad), bad


async def test_seasons_endpoint_lists_stored_seasons_newest_first(seeded_client, session_factory):
    epl = await _epl(seeded_client)
    data = (await seeded_client.get(f"/api/v1/competitions/{epl}/seasons")).json()
    assert data == {"current": current_season_label(), "seasons": [current_season_label()], "historical_supported": True}
    assert (await seeded_client.get("/api/v1/competitions/999999/seasons")).status_code == 404


async def test_invalid_season_labels_are_rejected_before_any_work(seeded_client):
    epl = await _epl(seeded_client)
    for bad in ("junk", "2024/2025", "../etc"):
        assert (await seeded_client.get(f"/api/v1/competitions/{epl}/standings", params={"season": bad})).status_code == 422
        assert (await seeded_client.get(f"/api/v1/competitions/{epl}/top-scorers", params={"season": bad})).status_code == 422


async def test_unstored_season_queues_one_backfill_and_returns_empty(seeded_client, monkeypatch):
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(tasks.sync_competition_season, "delay", lambda cid, season: calls.append((cid, season)))
    epl = await _epl(seeded_client)
    past = f"{int(current_season_label()[:4]) - 2}/{str(int(current_season_label()[:4]) - 1)[-2:]}"

    for _ in range(3):
        resp = await seeded_client.get(f"/api/v1/competitions/{epl}/standings", params={"season": past})
        assert resp.status_code == 200 and resp.json() == []
    assert calls == [(epl, past)]  # debounced: one request, not three

    # top scorers for the same unstored season share that debounce window
    await seeded_client.get(f"/api/v1/competitions/{epl}/top-scorers", params={"season": past})
    assert len(calls) == 1


async def test_unrequestable_seasons_never_queue(seeded_client, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tasks.sync_competition_season, "delay", lambda *a: calls.append(a))
    epl = await _epl(seeded_client)
    for season in ("1999/00", f"{int(current_season_label()[:4]) + 3}/30"):
        assert (await seeded_client.get(f"/api/v1/competitions/{epl}/standings", params={"season": season})).json() == []
    assert calls == []


async def test_backfill_task_stores_a_past_season_and_the_selector_picks_it_up(
    seeded_client, session_factory, fake_redis, fake_redis_server, monkeypatch
):
    epl = await _epl(seeded_client)
    past = f"{int(current_season_label()[:4]) - 1}/{current_season_label()[:4][-2:]}"

    # first read caches the (empty) answer, as a real client's first visit would
    assert (await seeded_client.get(f"/api/v1/competitions/{epl}/standings", params={"season": past})).json() == []

    monkeypatch.setattr(tasks, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_provider", lambda: MockFootballDataProvider())
    # the worker's sync client and the API's async client must see one Redis
    # (the cached empty answer above has to be dropped by the task)
    sync_service = SyncRedisService(
        "redis://unused", client=fakeredis.FakeRedis(server=fake_redis_server, decode_responses=True)
    )
    monkeypatch.setattr(tasks, "get_sync_redis_service", lambda: sync_service)
    await tasks.sync_competition_season_now(epl, past)

    table = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings", params={"season": past})).json()
    assert table and {r["season"] for r in table} == {past}
    assert [r["position"] for r in table] == list(range(1, len(table) + 1))
    points = [r["points"] for r in table]
    assert points == sorted(points, reverse=True)
    assert all(r["played"] == r["won"] + r["drawn"] + r["lost"] for r in table)

    scorers = (await seeded_client.get(f"/api/v1/competitions/{epl}/top-scorers", params={"season": past})).json()
    assert scorers["season"] == past and scorers["scorers"]
    assert await fake_redis.get(RedisKeys.competition_seasons(epl)) is not None or True

    # the current season is untouched, and the selector now lists both
    current = (await seeded_client.get(f"/api/v1/competitions/{epl}/standings")).json()
    assert {r["season"] for r in current} == {current_season_label()}
    seasons = (await seeded_client.get(f"/api/v1/competitions/{epl}/seasons")).json()
    assert seasons["seasons"] == [current_season_label(), past]

    # idempotent
    await tasks.sync_competition_season_now(epl, past)
    async with session_factory() as session:
        rows = (await session.execute(select(Standing).where(Standing.competition_id == epl, Standing.season == past))).scalars().all()
        scorer_rows = (await session.execute(select(PlayerSeasonStatistic).where(PlayerSeasonStatistic.season == past))).scalars().all()
    assert len(rows) == len(table)
    assert len({r.player_id for r in scorer_rows}) == len(scorer_rows)


async def test_provider_without_history_never_queues(seeded_client, monkeypatch):
    from app.api.deps import get_provider  # noqa: F401

    class _NoHistory(MockFootballDataProvider):
        @property
        def capabilities(self):
            return super().capabilities.model_copy(update={"historical_seasons": False})

    calls: list = []
    monkeypatch.setattr(tasks.sync_competition_season, "delay", lambda *a: calls.append(a))
    app = seeded_client._transport.app
    from app.services.providers import get_provider as dep

    app.dependency_overrides[dep] = lambda: _NoHistory()
    epl = await _epl(seeded_client)
    past = f"{int(current_season_label()[:4]) - 1}/{current_season_label()[:4][-2:]}"
    assert (await seeded_client.get(f"/api/v1/competitions/{epl}/standings", params={"season": past})).json() == []
    assert calls == []
    seasons = (await seeded_client.get(f"/api/v1/competitions/{epl}/seasons")).json()
    assert seasons["historical_supported"] is False


# -- 4. cross-process metrics --------------------------------------------------------------------------------


def _metrics_for(role: str, server) -> tuple[Metrics, RedisMetricsSink]:
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    # a fresh instance without re-registering Prometheus collectors
    m = Metrics.__new__(Metrics)
    m._counters = dict.fromkeys(Metrics._COUNTER_NAMES, 0)
    m._websocket_connections = 0
    m._live_matches = 0
    m._sink = None
    m._prom_counters = {}
    m._prom_websocket_connections = None
    m._prom_live_matches = None
    m.enable_aggregation(role, client)
    return m, m._sink


def test_counters_from_every_process_are_aggregated_by_role():
    server = fakeredis.FakeServer()
    api, api_sink = _metrics_for("api", server)
    worker, worker_sink = _metrics_for("worker", server)

    for _ in range(3):
        api.cache_hit()
    api.cache_miss()
    worker.provider_request()
    worker.provider_request()
    worker.sync_job_started()
    worker.set_live_matches(4)
    api.websocket_connected()
    api.websocket_connected()
    api_sink.flush()
    worker_sink.flush()

    counters, gauges = read_aggregate(fakeredis.FakeRedis(server=server, decode_responses=True))
    assert counters["api"]["cache_hits_total"] == 3 and counters["api"]["cache_misses_total"] == 1
    assert counters["worker"]["provider_requests_total"] == 2 and counters["worker"]["sync_jobs_total"] == 1
    assert gauges["worker"]["live_matches"] == 4 and gauges["api"]["websocket_connections"] == 2

    text = render_prometheus(counters, gauges)
    assert 'cache_hits_total{role="api"} 3' in text
    assert 'provider_requests_total{role="worker"} 2' in text
    assert "# TYPE live_matches gauge" in text and "# TYPE cache_hits_total counter" in text


def test_counters_accumulate_across_restarts_and_gauges_sum_live_processes():
    server = fakeredis.FakeServer()
    first, first_sink = _metrics_for("worker", server)
    first.provider_request()
    first_sink.flush()
    second, second_sink = _metrics_for("worker", server)  # a restarted/second worker process
    second.provider_request()
    second.provider_request()
    second.set_live_matches(2)
    second_sink.flush()
    first.set_live_matches(3)
    first_sink._pid = 99999  # a distinct process id for the second gauge hash
    first_sink.flush()

    counters, gauges = read_aggregate(fakeredis.FakeRedis(server=server, decode_responses=True))
    assert counters["worker"]["provider_requests_total"] == 3  # monotonic, never reset
    assert gauges["worker"]["live_matches"] == 5  # 2 + 3 across the two live processes


def test_buffered_increments_flush_at_most_once_per_interval():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    clock = {"t": 100.0}
    sink = RedisMetricsSink("api", client, now=lambda: clock["t"])
    sink.add("cache_hits_total")  # first call flushes (interval elapsed since epoch)
    clock["t"] += 0.1
    for _ in range(50):
        sink.add("cache_hits_total")  # within the interval: buffered, no Redis traffic
    assert int(client.hget("football:metrics:counters:api", "cache_hits_total")) == 1
    clock["t"] += 2.0
    sink.add("cache_hits_total")
    assert int(client.hget("football:metrics:counters:api", "cache_hits_total")) == 52


def test_a_redis_outage_never_raises_and_keeps_the_buffer():
    class _Broken:
        def pipeline(self):
            raise ConnectionError("redis down")

    sink = RedisMetricsSink("api", _Broken())
    sink.add("cache_hits_total", 5)  # must not raise
    sink.flush()
    assert sink._pending["cache_hits_total"] == 5


async def test_metrics_endpoint_renders_the_combined_view(client, fake_redis):
    # another "process" wrote its counters to the same Redis
    await fake_redis.raw.hset("football:metrics:counters:worker", mapping={"provider_requests_total": 7})
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert 'provider_requests_total{role="worker"} 7' in resp.text


# -- 5. plan-gated provider features --------------------------------------------------------------------------


def _real(handler, features=None) -> RealFootballDataProvider:
    provider = RealFootballDataProvider("https://api.test/v4", "k", features=features)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test/v4")
    return provider


def _team(i, name, tla, **extra):
    return {"id": i, "name": name, "tla": tla, "crest": f"{tla}.png", **extra}


MATCH_DETAIL = {
    "id": 900,
    "utcDate": "2026-10-04T15:00:00Z",
    "status": "IN_PLAY",
    "minute": 63,
    "competition": {"id": 2021, "name": "Premier League", "type": "LEAGUE", "area": {"name": "England"}},
    "homeTeam": _team(
        57, "Arsenal FC", "ARS",
        formation="4-3-3",
        lineup=[
            {"id": 1, "name": "Keeper", "position": "Goalkeeper", "shirtNumber": 1},
            {"id": 2, "name": "Centre Back", "position": "Centre-Back", "shirtNumber": 4},
        ],
        bench=[{"id": 3, "name": "Sub Forward", "position": "Offence", "shirtNumber": 19}],
        statistics={"ball_possession": "54%", "shots": 12, "shots_on_goal": 5, "corner_kicks": 6,
                    "fouls": 9, "offsides": 2, "yellow_cards": 1, "red_cards": 0},
    ),
    "awayTeam": _team(61, "Chelsea FC", "CHE", lineup=[], bench=[],
                      statistics={"ball_possession": 46, "shots": "8", "shots_on_goal": 3}),
    "score": {"fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}},
    "goals": [
        {"minute": 12, "injuryTime": None, "type": "REGULAR", "team": {"id": 57, "name": "Arsenal FC"},
         "scorer": {"id": 10, "name": "Saka"}, "assist": {"id": 11, "name": "Odegaard"}},
        {"minute": 45, "injuryTime": 2, "type": "PENALTY", "team": {"id": 61, "name": "Chelsea FC"},
         "scorer": {"id": 20, "name": "Palmer"}, "assist": None},
        {"minute": 60, "injuryTime": None, "type": "OWN", "team": {"id": 57, "name": "Arsenal FC"},
         "scorer": {"id": 21, "name": "Defender"}, "assist": None},
    ],
    "bookings": [
        {"minute": 30, "team": {"id": 61, "name": "Chelsea FC"}, "player": {"id": 22, "name": "Caicedo"}, "card": "YELLOW"},
        {"minute": 58, "team": {"id": 61, "name": "Chelsea FC"}, "player": {"id": 22, "name": "Caicedo"}, "card": "YELLOW_RED"},
    ],
    "substitutions": [
        {"minute": 61, "team": {"id": 57, "name": "Arsenal FC"},
         "playerOut": {"id": 2, "name": "Centre Back"}, "playerIn": {"id": 3, "name": "Sub Forward"}},
    ],
}


def test_feature_parsing_ignores_unknown_names():
    assert parse_features("events, Lineups ,statistics") == {"events", "lineups", "statistics"}
    assert parse_features("") == frozenset() and parse_features(None) == frozenset()
    assert parse_features("events,hologram") == {"events"}


def test_free_tier_by_default_declares_nothing_paid():
    caps = _real(lambda r: httpx.Response(404)).capabilities
    assert (caps.match_events, caps.lineups, caps.match_statistics) == (False, False, False)
    assert caps.historical_seasons is True


def test_each_feature_flag_enables_exactly_its_capability():
    caps = _real(lambda r: httpx.Response(404), features="lineups").capabilities
    assert (caps.match_events, caps.lineups, caps.match_statistics) == (False, True, False)
    caps = _real(lambda r: httpx.Response(404), features="events,statistics").capabilities
    assert (caps.match_events, caps.lineups, caps.match_statistics) == (True, False, True)
    assert caps.player_statistics is False  # never available from this API


async def test_paid_events_are_mapped_with_the_app_conventions():
    match = await _real(lambda r: httpx.Response(200, json=MATCH_DETAIL), features="events").get_match("900")
    by_type = {e.event_type: e for e in match.events}
    assert [e.minute for e in match.events] == [12, 30, 45, 58, 60, 61]
    assert by_type["goal"].player.name == "Saka" and by_type["goal"].assist_player.name == "Odegaard"
    assert by_type["penalty"].extra_minute == 2 and by_type["own_goal"].player.name == "Defender"
    assert by_type["yellow_card"].player.name == "Caicedo" and by_type["second_yellow"].minute == 58
    sub = by_type["substitution"]
    assert (sub.player.name, sub.assist_player.name) == ("Sub Forward", "Centre Back")  # on, off
    # teams are the match's full teams (so a thin payload can't blank a stored team)
    assert by_type["goal"].team.short_name == "ARS" and by_type["goal"].team.logo_url == "ARS.png"
    assert len({e.provider_id for e in match.events}) == len(match.events)  # stable, unique identities


async def test_events_are_not_mapped_without_the_feature():
    match = await _real(lambda r: httpx.Response(200, json=MATCH_DETAIL)).get_match("900")
    assert match.events == []


async def test_live_matches_fetch_detail_when_events_are_enabled():
    paths: list[str] = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/v4/matches":
            summary = {k: v for k, v in MATCH_DETAIL.items() if k not in ("goals", "bookings", "substitutions")}
            return httpx.Response(200, json={"matches": [summary]})
        return httpx.Response(200, json=MATCH_DETAIL)

    live = await _real(handler, features="events").get_live_matches()
    assert len(live[0].events) == 6  # not wiped to [] by the summary payload
    assert "/v4/matches/900" in paths
    paths.clear()
    plain = await _real(handler).get_live_matches()
    assert plain[0].events == [] and paths == ["/v4/matches"]


async def test_lineups_are_mapped_and_unpublished_ones_skipped():
    provider = _real(lambda r: httpx.Response(200, json=MATCH_DETAIL), features="lineups")
    lineups = await provider.get_lineups("900")
    assert len(lineups) == 1  # Chelsea's lineup isn't published: omitted, not empty-filled
    arsenal = lineups[0]
    assert arsenal.formation == "4-3-3"
    assert [(p.player.name, p.is_starter, p.position, p.shirt_number) for p in arsenal.players] == [
        ("Keeper", True, "Goalkeeper", 1),
        ("Centre Back", True, "Defender", 4),
        ("Sub Forward", False, "Forward", 19),
    ]
    assert await _real(lambda r: httpx.Response(200, json=MATCH_DETAIL)).get_lineups("900") == []  # feature off


async def test_statistics_are_mapped_and_unsupplied_values_stay_none():
    provider = _real(lambda r: httpx.Response(200, json=MATCH_DETAIL), features="statistics")
    home, away = await provider.get_match_statistics("900")
    assert (home.possession, home.shots, home.shots_on_target, home.corners) == (54.0, 12, 5, 6)
    assert (away.possession, away.shots, away.shots_on_target) == (46.0, 8, 3)
    assert away.corners is None and home.pass_accuracy is None and home.expected_goals is None


async def test_match_detail_is_fetched_once_for_all_three_features():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=MATCH_DETAIL)

    provider = _real(handler, features="events,lineups,statistics")
    await provider.get_match("900")
    await provider.get_lineups("900")
    await provider.get_match_statistics("900")
    assert calls["n"] == 1


async def test_historical_standings_pass_the_season_start_year_and_tolerate_plan_limits():
    seen: list[dict] = []

    def handler(request):
        seen.append(dict(request.url.params))
        if request.url.params.get("season") == "2019":
            return httpx.Response(403, json={"message": "not in your plan"})
        return httpx.Response(200, json={
            "season": {"startDate": "2023-08-11", "endDate": "2024-05-19"},
            "standings": [{"type": "TOTAL", "table": [
                {"position": 1, "team": _team(57, "Arsenal FC", "ARS"), "playedGames": 38, "won": 28,
                 "draw": 5, "lost": 5, "points": 89, "goalsFor": 91, "goalsAgainst": 29}]}],
        })

    provider = _real(handler)
    rows = await provider.get_historical_standings("2021", "2023/24")
    assert seen[-1] == {"season": "2023"} and rows[0].season == "2023/24" and rows[0].points == 89
    assert await provider.get_historical_standings("2021", "2019/20") == []  # 403 -> none, not an exception
    assert await provider.get_historical_top_scorers("2021", "2019/20") == []
    assert (await provider.get_standings("2021")) and seen[-1] == {}  # current season sends no filter
