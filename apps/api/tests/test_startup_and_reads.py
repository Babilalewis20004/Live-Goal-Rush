"""Start-up behaviour and the rule that reads never depend on the football provider (Phase 7)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.models.competition import Competition
from app.models.match import Match
from app.services import seed
from app.services.football_service import FootballService
from tests.fakes.mock_provider import MockFootballDataProvider


class CountingProvider(MockFootballDataProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def get_competitions(self):
        self.calls += 1
        return await super().get_competitions()


def _patch_seed(monkeypatch, session_factory, provider):
    monkeypatch.setattr(seed, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(seed, "get_provider", lambda: provider)


async def test_an_empty_database_is_seeded_from_the_provider(session_factory, monkeypatch, test_engine):
    provider = CountingProvider()
    _patch_seed(monkeypatch, session_factory, provider)
    await seed.seed_database()
    assert provider.calls >= 1
    async with session_factory() as db:
        assert (await db.scalar(select(Competition.id))) is not None


async def test_a_recently_synced_database_does_not_spend_provider_quota_on_every_restart(session_factory, monkeypatch, test_engine):
    first = CountingProvider()
    _patch_seed(monkeypatch, session_factory, first)
    await seed.seed_database()
    assert first.calls >= 1

    restart = CountingProvider()
    _patch_seed(monkeypatch, session_factory, restart)
    for _ in range(3):  # three restarts / scale-out events in a row
        await seed.seed_database()
    assert restart.calls == 0


async def test_a_stale_database_is_refreshed_on_start(session_factory, monkeypatch, test_engine):
    provider = CountingProvider()
    _patch_seed(monkeypatch, session_factory, provider)
    await seed.seed_database()
    async with session_factory() as db:
        await db.execute(update(Match).values(last_synced_at=datetime.now(timezone.utc) - timedelta(days=2)))
        await db.commit()
    provider.calls = 0
    await seed.seed_database()
    assert provider.calls >= 1


async def test_the_competition_list_is_served_from_stored_data_not_the_provider(client, session_factory):
    from app.api.deps import get_provider

    async with session_factory() as db:
        await FootballService(db=db, provider=MockFootballDataProvider()).sync_all_competitions_and_fixtures()

    provider = CountingProvider()
    client._transport.app.dependency_overrides[get_provider] = lambda: provider
    for _ in range(3):
        resp = await client.get("/api/v1/competitions")
        assert resp.status_code == 200 and resp.json()["total"] > 0
    assert provider.calls == 0


async def test_a_brand_new_empty_database_still_bootstraps_the_competition_list(client):
    resp = await client.get("/api/v1/competitions")
    assert resp.status_code == 200 and resp.json()["total"] > 0  # the one case that may ask the provider


# -- search caching (Phase 7) ----------------------------------------------------------------------------------------------


async def test_repeated_searches_are_answered_from_the_cache(seeded_client, fake_redis, monkeypatch):
    calls = []

    first = await seeded_client.get("/api/v1/search", params={"q": "arsenal"})
    assert first.status_code == 200 and first.json()["teams"]
    assert await fake_redis.raw.exists("football:search:results:10:arsenal") == 1
    assert 0 < await fake_redis.raw.ttl("football:search:results:10:arsenal") <= 30

    from app.services.football_service import FootballService

    async def forbidden(*_a, **_k):
        calls.append(1)
        raise AssertionError("the database search must not run for a cached query")

    monkeypatch.setattr(FootballService, "search", forbidden)
    again = await seeded_client.get("/api/v1/search", params={"q": "ARSENAL"})  # normalised to the same key
    assert again.status_code == 200 and again.json() == first.json() and not calls


async def test_the_search_cache_is_keyed_by_result_limit_and_is_public_data(seeded_client, fake_redis, make_user):
    await seeded_client.get("/api/v1/search", params={"q": "manchester", "limit": 3})
    await seeded_client.get("/api/v1/search", params={"q": "manchester", "limit": 10})
    keys = {k async for k in fake_redis.raw.scan_iter("football:search:results:*")}
    assert keys == {"football:search:results:3:manchester", "football:search:results:10:manchester"}
    # no user-specific state is involved: the same cached answer serves a signed-in visitor
    _u, headers = await make_user("signed@example.com")
    cached = await seeded_client.get("/api/v1/search", params={"q": "manchester", "limit": 10}, headers=headers)
    anonymous = await seeded_client.get("/api/v1/search", params={"q": "manchester", "limit": 10})
    assert cached.json() == anonymous.json()


async def test_search_still_works_when_the_cache_is_unavailable(client, session_factory, monkeypatch):
    from app.core.redis_client import RedisService

    async def down(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(RedisService, "get", down)
    monkeypatch.setattr(RedisService, "set", down)
    async with session_factory() as db:
        await FootballService(db=db, provider=MockFootballDataProvider()).sync_all_competitions_and_fixtures()
    resp = await client.get("/api/v1/search", params={"q": "arsenal"})
    assert resp.status_code == 200 and resp.json()["teams"]
