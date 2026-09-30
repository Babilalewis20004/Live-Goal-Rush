"""Phase 4 end-to-end scenario, using the real components: a scripted
provider -> the worker's real sync+publish code (`tasks._sync_one_match`)
-> PostgreSQL -> Redis cache + Pub/Sub -> the real `PubSubBridge` ->
the real `ConnectionManager` (fake socket objects) -> the REST API.

Only three seams are substituted: the provider (scripted), Redis (fakeredis
sharing one in-memory server between the sync client the worker uses and the
async client the API/bridge use) and Celery's broker (`.delay` is recorded).
The worker's DB session factory is pointed at the test database.

What this does NOT cover: the web and mobile UIs themselves. Their reducers
(`applyRealtimeMessage`) and components are covered by the vitest/tsc/eslint
suites; steps 13/14/17 of the scenario are verified there, not in a browser.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
import pytest_asyncio
from fakeredis import aioredis as fakeredis_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.redis_client import RedisService, SyncRedisService, get_redis_service
from app.core.redis_keys import RedisKeys
from app.db.session import get_db
from app.main import create_app
from app.services.providers import get_provider
from app.services.providers import mock_extras
from app.services.providers.mock_data import FIXTURES
from app.services.providers.mock_provider import MockFootballDataProvider, _player_from_dict, _team
from app.services.providers.schemas import (
    ProviderMatch,
    ProviderMatchEvent,
    ProviderPlayer,
    ProviderTeamMatchStatistics,
)
from app.websocket.manager import ConnectionManager
from app.websocket.pubsub_bridge import PubSubBridge
from app.worker import notification_tasks, tasks

PROVIDER_MATCH_ID = "e2e-1"


class ScriptedProvider(MockFootballDataProvider):
    """One Liverpool v Chelsea match whose state the test moves forward."""

    def __init__(self) -> None:
        self.status = "live"
        self.minute: int | None = 10
        self.home = 0
        self.away = 0
        self.events: list[ProviderMatchEvent] = []
        self.lineups_published = False
        self.shots_home: int | None = None
        self.finished_table = False
        self.kickoff = datetime.now(timezone.utc) - timedelta(minutes=10)

    def match(self) -> ProviderMatch:
        base = next(m for m in self._all_matches() if m.provider_id == "epl-1")
        return ProviderMatch(
            provider_id=PROVIDER_MATCH_ID,
            competition=base.competition,
            home_team=base.home_team,
            away_team=base.away_team,
            kickoff_time=self.kickoff,
            status=self.status,
            home_score=self.home,
            away_score=self.away,
            minute=self.minute,
            venue="Anfield",
            events=list(self.events),
        )

    async def get_live_matches(self):
        return [self.match()] if self.status in ("live", "halftime") else []

    async def get_match(self, match_id):
        return self.match() if match_id == PROVIDER_MATCH_ID else None

    async def get_lineups(self, match_id):
        return await super().get_lineups("epl-1") if self.lineups_published else []

    async def get_match_statistics(self, match_id):
        if self.shots_home is None:
            return []
        return [
            ProviderTeamMatchStatistics(team=_team("t-liv"), possession=55.0, shots=self.shots_home),
            ProviderTeamMatchStatistics(team=_team("t-che"), possession=45.0, shots=2),
        ]

    async def get_player_statistics(self, match_id):
        return []

    async def get_standings(self, competition_id):
        rows = await super().get_standings(competition_id)
        if self.finished_table:
            liverpool = next(r for r in rows if r.team.provider_id == "t-liv")
            liverpool.points += 3
            liverpool.won += 1
            liverpool.played += 1
        return rows


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


async def _wait_for(predicate, timeout=3.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest_asyncio.fixture
async def pipeline(test_engine, monkeypatch):
    server = fakeredis.FakeServer()
    async_redis = RedisService(
        settings.redis_url, client=fakeredis_aioredis.FakeRedis(server=server, decode_responses=True)
    )
    sync_redis = SyncRedisService(settings.redis_url, client=fakeredis.FakeRedis(server=server, decode_responses=True))
    provider = ScriptedProvider()
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    # the worker
    monkeypatch.setattr(tasks, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_sync_redis_service", lambda: sync_redis)
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    queued_standings: list[int] = []
    monkeypatch.setattr(tasks.sync_competition_standings, "delay", lambda cid: queued_standings.append(cid))
    notified: list[str] = []
    monkeypatch.setattr(
        notification_tasks.dispatch_notifications, "delay", lambda payload: notified.append(payload["type"])
    )

    # the API
    app = create_app()

    async def _db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_redis_service] = lambda: async_redis

    # the real-time fan-out
    mgr = ConnectionManager()
    bridge = PubSubBridge(redis=async_redis, manager=mgr)
    bridge.start()
    await asyncio.sleep(0.1)  # let the bridge subscribe before anything publishes

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "client": client,
            "provider": provider,
            "redis": async_redis,
            "manager": mgr,
            "queued_standings": queued_standings,
            "notified": notified,
        }
    await bridge.stop()


async def _poll(provider: ScriptedProvider) -> None:
    """One worker cycle for the match, exactly as `sync_live_matches` /
    `sync_post_match` do it."""
    await tasks._sync_one_match(provider, provider.match())


def _types(socket: _FakeSocket) -> list[str]:
    return [m["type"] for m in socket.sent]


async def test_full_match_centre_scenario(pipeline):
    client, provider, redis = pipeline["client"], pipeline["provider"], pipeline["redis"]
    manager = pipeline["manager"]

    # 1-3. The provider returns a live match; the worker syncs it into Postgres.
    await _poll(provider)
    live = (await client.get("/api/v1/matches/live")).json()
    assert [m["home_team"]["name"] for m in live] == ["Liverpool"]
    match_id = live[0]["id"]
    competition_id = live[0]["competition"]["id"]
    liverpool_id = live[0]["home_team"]["id"]
    await tasks.sync_competition_standings_now(competition_id)  # the periodic standings sync

    # 4-6. A user opens the match centre: REST serves it and the read is cached in Redis.
    detail = (await client.get(f"/api/v1/matches/{match_id}")).json()
    assert (detail["status"], detail["home_score"], detail["away_score"], detail["minute"]) == ("live", 0, 0, 10)
    assert await redis._client.exists(RedisKeys.match(match_id)) == 1
    # empty lineups/statistics are real, cacheable answers -- they must be refreshed when data arrives
    assert (await client.get(f"/api/v1/matches/{match_id}/lineups")).json() == {"home": None, "away": None}
    assert (await client.get(f"/api/v1/matches/{match_id}/statistics")).json() == {"home": None, "away": None}
    table_before = (await client.get(f"/api/v1/competitions/{competition_id}/standings")).json()
    form_before = (await client.get(f"/api/v1/teams/{liverpool_id}/form")).json()
    assert await redis._client.exists(RedisKeys.competition_standings(competition_id)) == 1
    liverpool_row_before = next(r for r in table_before if r["team"]["id"] == liverpool_id)

    # 7. A WebSocket client connects for this match.
    socket = _FakeSocket()
    await manager.connect_match(socket, str(match_id))
    general = _FakeSocket()
    await manager.connect_general(general)

    # 8-12. The provider reports a goal -> worker detects it -> DB updated -> Redis event -> WebSocket.
    provider.events.append(
        ProviderMatchEvent(
            provider_id="e2e-goal-1",
            event_type="goal",
            minute=12,
            team=_team("t-liv"),
            player=ProviderPlayer(provider_id="p-salah", name="Salah", position="Forward"),
        )
    )
    provider.home, provider.minute = 1, 12
    await _poll(provider)
    assert await _wait_for(lambda: "GOAL" in _types(socket))
    goal = next(m for m in socket.sent if m["type"] == "GOAL")
    assert goal["match"]["id"] == str(match_id) and goal["match"]["home_score"] == 1
    assert goal["match"]["event"]["player"] == "Salah"
    assert "GOAL" in _types(general)  # the general feed gets it too
    assert (await client.get(f"/api/v1/matches/{match_id}")).json()["home_score"] == 1  # cache was invalidated

    # 15-17. Lineups are published -> LINEUP_UPDATED -> the match centre shows them.
    provider.lineups_published = True
    await _poll(provider)
    assert await _wait_for(lambda: "LINEUP_UPDATED" in _types(socket))
    lineups = (await client.get(f"/api/v1/matches/{match_id}/lineups")).json()
    assert len(lineups["home"]["starters"]) == 11 and len(lineups["away"]["substitutes"]) == 7
    assert lineups["home"]["formation"] == "4-3-3"

    # A substitution refreshes the (cached) lineup with subbed in/out minutes.
    home_lineup = mock_extras.build_lineup(next(f for f in FIXTURES if f["provider_id"] == "epl-1"), "home")
    coming_on, going_off = home_lineup["bench"][0], home_lineup["starters"][5]
    provider.events.append(
        ProviderMatchEvent(
            provider_id="e2e-sub-1",
            event_type="substitution",
            minute=60,
            team=_team("t-liv"),
            player=_player_from_dict(coming_on),
            assist_player=_player_from_dict(going_off),
        )
    )
    provider.minute = 60
    await _poll(provider)
    assert await _wait_for(lambda: "SUBSTITUTION" in _types(socket))
    lineups = (await client.get(f"/api/v1/matches/{match_id}/lineups")).json()
    by_name = {p["player"]["name"]: p for p in lineups["home"]["starters"] + lineups["home"]["substitutes"]}
    assert by_name[coming_on["name"]]["subbed_in_minute"] == 60
    assert by_name[going_off["name"]]["subbed_out_minute"] == 60

    # 18-19. Statistics arrive, then update; an unchanged poll broadcasts nothing.
    provider.shots_home = 5
    await _poll(provider)
    assert await _wait_for(lambda: "STATISTICS_UPDATED" in _types(socket))
    stats_event = next(m for m in socket.sent if m["type"] == "STATISTICS_UPDATED")
    assert stats_event["match"]["statistics"]["home"]["shots"] == 5
    assert (await client.get(f"/api/v1/matches/{match_id}/statistics")).json()["home"]["shots"] == 5

    provider.shots_home = 6
    await _poll(provider)
    assert await _wait_for(lambda: _types(socket).count("STATISTICS_UPDATED") == 2)
    assert (await client.get(f"/api/v1/matches/{match_id}/statistics")).json()["home"]["shots"] == 6

    settled = len(socket.sent)
    await _poll(provider)  # nothing changed at all
    await asyncio.sleep(0.2)
    assert len(socket.sent) == settled

    # 20-21. Full time: final score stored, MATCH_FINISHED broadcast, standings sync queued.
    provider.status, provider.minute, provider.finished_table = "finished", None, True
    await _poll(provider)
    assert await _wait_for(lambda: "MATCH_FINISHED" in _types(socket))
    final = (await client.get(f"/api/v1/matches/{match_id}")).json()
    assert (final["status"], final["home_score"], final["away_score"]) == ("finished", 1, 0)
    assert pipeline["queued_standings"] == [competition_id]  # only the finish queued it, not the live goal

    # 22-23. The queued standings sync runs; the competition table (and team form) update.
    assert await redis._client.exists(RedisKeys.competition_standings(competition_id)) == 0  # dropped on finish
    await tasks.sync_competition_standings_now(competition_id)
    table_after = (await client.get(f"/api/v1/competitions/{competition_id}/standings")).json()
    liverpool_row_after = next(r for r in table_after if r["team"]["id"] == liverpool_id)
    assert liverpool_row_after["points"] == liverpool_row_before["points"] + 3
    assert liverpool_row_after["played"] == liverpool_row_before["played"] + 1
    assert len(table_after) == len(table_before)  # updated in place, no duplicate rows

    form_after = (await client.get(f"/api/v1/teams/{liverpool_id}/form")).json()
    assert form_after["results"][0]["match_id"] == match_id and form_after["results"][0]["result"] == "W"
    assert form_after["results"] != form_before["results"]

    # Notifications: goal and full time were dispatched; match-centre refresh signals never are.
    notified = pipeline["notified"]
    assert "GOAL" in notified and "MATCH_FINISHED" in notified
    assert "LINEUP_UPDATED" not in notified and "STATISTICS_UPDATED" not in notified


async def test_live_standings_do_not_change_until_the_match_finishes(pipeline):
    """A goal during a live match must not re-sync official standings (§19)."""
    client, provider = pipeline["client"], pipeline["provider"]
    await _poll(provider)
    provider.events.append(
        ProviderMatchEvent(provider_id="g1", event_type="goal", minute=5, team=_team("t-liv"),
                           player=ProviderPlayer(provider_id="p-salah", name="Salah"))
    )
    provider.home, provider.minute = 1, 5
    await _poll(provider)
    assert pipeline["queued_standings"] == []
    del client
