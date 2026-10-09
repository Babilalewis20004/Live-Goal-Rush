"""Behaviour when a dependency is down (Phase 7 §9, §14, AB): Redis, the football provider, the database.

The contract (docs/operations/failure-modes.md): reads keep working from Postgres when Redis is gone, abuse
limits fail OPEN for ordinary traffic (an outage must not lock everyone out), the football provider being down
never turns a stored-data read into an error, and a database outage is a retryable 503, never a 500 or a hang."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_storage_dep
from app.core.redis_client import RedisService, get_redis_service
from app.db.session import get_db
from app.main import create_app
from app.services.providers import get_provider
from tests.fakes.mock_provider import MockFootballDataProvider

API = "/api/v1"


class _DeadClient:
    """Every operation raises, like a Redis that has gone away."""

    def __getattr__(self, name):
        async def boom(*_a, **_k):
            raise ConnectionError("Redis is down")

        def pipeline(*_a, **_k):
            raise ConnectionError("Redis is down")

        return pipeline if name == "pipeline" else boom


@pytest.fixture
def dead_redis() -> RedisService:
    return RedisService("redis://unused", client=_DeadClient())


@pytest.fixture
async def no_redis_client(test_engine, dead_redis, memory_storage):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _db():
        async with session_local() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_provider] = lambda: MockFootballDataProvider()
    app.dependency_overrides[get_redis_service] = lambda: dead_redis
    app.dependency_overrides[get_storage_dep] = lambda: memory_storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def seeded_no_redis(no_redis_client, test_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.football_service import FootballService

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        await FootballService(db=session, provider=MockFootballDataProvider()).sync_all_competitions_and_fixtures()
    return no_redis_client


# -- Redis down -----------------------------------------------------------------------------------------------------------

PUBLIC_READS = [
    "/matches/live", "/matches/today", "/matches/upcoming", "/competitions", "/capabilities",
    "/articles", "/discovery/home", "/discovery/trending", "/search?q=arsenal", "/search/suggestions?q=ars",
    "/search/popular", "/subscription/plans", "/polls", "/ads/placements",
]


@pytest.mark.parametrize("path", PUBLIC_READS)
async def test_public_reads_survive_a_redis_outage(seeded_no_redis, path):
    resp = await seeded_no_redis.get(f"{API}{path}")
    assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text[:200]}"


async def test_match_pages_are_served_from_the_database_without_redis(seeded_no_redis, get_match_id):
    match_id = await get_match_id("epl-3")
    for suffix in ("", "/events", "/lineups", "/statistics", "/form", "/head-to-head"):
        resp = await seeded_no_redis.get(f"{API}/matches/{match_id}{suffix}")
        assert resp.status_code == 200, f"/matches/{match_id}{suffix}: {resp.status_code} {resp.text[:200]}"


async def test_team_competition_and_player_pages_survive_a_redis_outage(seeded_no_redis, lookup):
    from app.models.competition import Competition
    from app.models.team import Team

    team_id, comp_id = await lookup(Team, "Arsenal"), await lookup(Competition, "Premier League")
    for path in (f"/teams/{team_id}", f"/teams/{team_id}/fixtures", f"/teams/{team_id}/players", f"/competitions/{comp_id}", f"/competitions/{comp_id}/standings"):
        resp = await seeded_no_redis.get(f"{API}{path}")
        assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text[:200]}"


async def test_signing_in_and_account_use_still_work_without_redis(no_redis_client):
    """Rate limiting fails open: during an outage people can still register and sign in."""
    body = {"email": "outage@example.com", "password": "Sup3rSecret!", "password_confirm": "Sup3rSecret!"}
    reg = await no_redis_client.post(f"{API}/auth/register", json=body, headers={"X-Client": "mobile"})
    assert reg.status_code == 201, reg.text
    token = reg.json()["tokens"]["access_token"]
    login = await no_redis_client.post(f"{API}/auth/login", json={"email": "outage@example.com", "password": "Sup3rSecret!"})
    assert login.status_code == 200
    me = await no_redis_client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


async def test_community_reads_and_writes_survive_a_redis_outage(no_redis_client, make_user, session_factory):
    from app.models.community import Comment  # noqa: F401

    _u, headers = await make_user("commenter@example.com")
    posted = await no_redis_client.post(f"{API}/comments", json={"target_type": "match", "target_id": 1, "body": "still here"}, headers=headers)
    assert posted.status_code in (201, 404), posted.text  # 404: no such match in this empty database; never a 500
    assert (await no_redis_client.get(f"{API}/comments", params={"target_type": "match", "target_id": 1})).status_code in (200, 404)


async def test_billing_state_does_not_depend_on_redis(no_redis_client, make_user):
    _u, headers = await make_user("payer@example.com")
    assert (await no_redis_client.get(f"{API}/subscription", headers=headers)).status_code == 200
    assert (await no_redis_client.get(f"{API}/me/entitlements", headers=headers)).json()["premium"] is False


async def test_readiness_reports_the_outage_but_liveness_does_not(no_redis_client):
    assert (await no_redis_client.get("/health/live")).status_code == 200
    ready = await no_redis_client.get("/health/ready")
    assert ready.status_code == 503 and ready.json()["dependencies"]["redis"] == "unavailable"
    assert ready.json()["dependencies"]["database"] == "ok"


async def test_the_metrics_endpoint_falls_back_to_local_counters_without_redis(no_redis_client):
    resp = await no_redis_client.get("/metrics")
    assert resp.status_code == 200 and "http_requests_total" in resp.text


# -- football provider down ----------------------------------------------------------------------------------------------------


class DownProvider(MockFootballDataProvider):
    """Every call fails the way a refused connection or an exhausted quota does."""

    def __getattribute__(self, name):
        if name.startswith("get_") or name == "search":
            async def boom(*_a, **_k):
                raise ConnectionError("provider unreachable")

            return boom
        return super().__getattribute__(name)


@pytest.fixture
async def provider_down_client(client, test_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.football_service import FootballService

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:  # data was synced while the provider was healthy
        await FootballService(db=session, provider=MockFootballDataProvider()).sync_all_competitions_and_fixtures()
    client._transport.app.dependency_overrides[get_provider] = lambda: DownProvider()
    return client


@pytest.mark.parametrize(
    "path",
    ["/competitions", "/matches/today", "/matches/live", "/matches/upcoming", "/search?q=arsenal", "/search?q=zzzzqq", "/search/suggestions?q=ars", "/discovery/home"],
)
async def test_reads_never_fail_because_the_provider_is_down(provider_down_client, path):
    resp = await provider_down_client.get(f"{API}{path}")
    assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text[:200]}"

async def test_a_brand_new_database_with_the_provider_down_lists_no_competitions_instead_of_a_500(client):
    """A first deploy with a bad or exhausted provider key: nothing seeded yet, so nothing to show -- but not a 500."""
    client._transport.app.dependency_overrides[get_provider] = lambda: DownProvider()
    resp = await client.get(f"{API}/competitions")
    assert resp.status_code == 200
    assert resp.json()["items"] == [] if "items" in resp.json() else resp.json() == []


async def test_search_with_no_local_match_returns_empty_not_an_error_when_the_provider_is_down(provider_down_client):
    resp = await provider_down_client.get(f"{API}/search", params={"q": "nonexistent club name"})
    assert resp.status_code == 200
    assert resp.json()["teams"] == [] and resp.json()["players"] == []


async def test_stale_data_is_marked_not_hidden(provider_down_client, session_factory):
    """With the provider gone, matches keep being served and say how old they are (data_status), per Phase 2 §21."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.models.match import Match

    async with session_factory() as db:
        await db.execute(update(Match).values(last_synced_at=datetime.now(timezone.utc) - timedelta(hours=3)))
        await db.commit()
    resp = await provider_down_client.get(f"{API}/matches/today")
    assert resp.status_code == 200
    statuses = {m["data_status"] for m in resp.json()}
    assert statuses and statuses <= {"STALE", "FRESH", "UNAVAILABLE"} and "FRESH" not in statuses


async def test_the_search_provider_fallback_has_a_budget(client, session_factory, monkeypatch):
    from app.core.config import settings

    calls = []

    class Counting(MockFootballDataProvider):
        async def search(self, query):
            calls.append(query)
            return await super().search(query)

    monkeypatch.setattr(settings, "search_provider_fallbacks_per_minute", 3)
    client._transport.app.dependency_overrides[get_provider] = lambda: Counting()
    for i in range(8):
        assert (await client.get(f"{API}/search", params={"q": f"unknownclub{i}"})).status_code == 200
    assert len(calls) <= 3  # eight different unknown queries cost at most three provider calls


# -- database down ----------------------------------------------------------------------------------------------------------------


async def test_a_database_outage_is_a_retryable_503_and_the_api_recovers(client, monkeypatch):
    """The first request after the database returns must succeed -- no restart needed."""
    from sqlalchemy.exc import OperationalError

    state = {"down": True}
    original = client._transport.app.dependency_overrides[get_db]

    async def flaky_db():
        if state["down"]:
            raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))
        async for session in original():
            yield session

    client._transport.app.dependency_overrides[get_db] = flaky_db
    down = await client.get(f"{API}/competitions")
    assert down.status_code == 503 and down.headers["retry-after"]
    assert (await client.get("/health/live")).status_code == 200  # the process itself is fine
    state["down"] = False
    assert (await client.get(f"{API}/competitions")).status_code == 200
