from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from fakeredis import aioredis as fakeredis_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.redis_client import RedisService, get_redis_service
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import (  # noqa: F401
    competition,
    device,
    favourite,
    match,
    match_event,
    notification,
    player,
    session as session_model,
    standing,
    team,
    user,
)
from app.models.user import User
from app.services.football_service import FootballService
from app.services.providers import get_provider
from app.services.providers.mock_provider import MockFootballDataProvider

_ASYNC_PREFIX = "postgresql+asyncpg://"
_base_url, _, _dev_db_name = settings.database_url.removeprefix(_ASYNC_PREFIX).rpartition("/")
_TEST_DB_NAME = f"{_dev_db_name}_test"
TEST_DATABASE_URL = f"{_ASYNC_PREFIX}{_base_url}/{_TEST_DB_NAME}"


@pytest.fixture(autouse=True)
def _no_real_celery_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test needs a *real* Celery broker round trip -- `.delay()` calls
    reachable from HTTP endpoints (e.g. `sync_team.delay()` on following a
    team, in `favourites_service.py`) would otherwise try to publish to
    whatever `REDIS_URL` points at for real, which is slow (and flaky
    under load) for something no test asserts on. Patched at the base
    `Task` class so it covers every current and future `@celery_app.task`,
    not just the ones known about today. Tests that need to verify actual
    task *behavior* call the underlying function directly instead of going
    through `.delay()` (see `test_notification_dispatch.py`)."""
    from celery.app.task import Task

    monkeypatch.setattr(Task, "delay", lambda self, *args, **kwargs: None)


async def _ensure_test_database_exists() -> None:
    conn = await asyncpg.connect(f"postgresql://{_base_url}/postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """A fresh engine per test, bound to that test's own event loop --
    pytest-asyncio gives every test function a new loop, and asyncpg
    connections can't be reused across loops, so the engine (and its
    connection pool) must not outlive a single test either."""
    await _ensure_test_database_exists()
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[RedisService, None]:
    """An isolated in-memory Redis (via fakeredis) per test -- exercises
    the real cache-aside code path (JSON encode/decode, TTLs, pub/sub)
    without requiring a real Redis server for the test suite."""
    client = fakeredis_aioredis.FakeRedis(decode_responses=True)
    yield RedisService(settings.redis_url, client=client)
    await client.aclose()


@pytest_asyncio.fixture
async def client(test_engine: AsyncEngine, fake_redis: RedisService) -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client for the FastAPI app wired to a fresh test database, a
    fake in-memory Redis, and the mock provider. Does not run the app's
    startup seeding (the lifespan event is not triggered by ASGITransport)
    -- tests that need pre-seeded entities should use the `seeded_client`
    fixture instead."""
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_provider] = lambda: MockFootballDataProvider()
    app.dependency_overrides[get_redis_service] = lambda: fake_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_client(
    client: AsyncClient, test_engine: AsyncEngine
) -> AsyncGenerator[AsyncClient, None]:
    """Same as `client`, but with the test database pre-populated from the
    mock provider first -- mirrors what the app's startup lifespan does
    against the real database. Phase 2's read endpoints no longer sync
    on-read (see football_service.py), so any test that expects live/
    today/upcoming/competition/team data to already exist needs this."""
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        service = FootballService(db=session, provider=MockFootballDataProvider())
        await service.sync_all_competitions_and_fixtures()
    yield client


@pytest_asyncio.fixture
async def test_user(test_engine: AsyncEngine) -> AsyncGenerator[User, None]:
    """A single persisted user, independent of the `client`/`authenticated_client`
    fixtures so tests needing a *second* user (cross-user isolation checks)
    can create one directly instead."""
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        instance = User(
            email="test@example.com",
            hashed_password=hash_password("Sup3rSecret!"),
            display_name="Test User",
        )
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    yield instance


@pytest_asyncio.fixture
async def authenticated_client(client: AsyncClient, test_user: User) -> AsyncGenerator[AsyncClient, None]:
    """Same as `client`, but with a valid `access_token` cookie already set
    for `test_user` -- mints the token directly rather than going through
    `/auth/login`, since most tests using this fixture care about the
    endpoint under test, not re-proving login works (that's `test_auth.py`'s
    job)."""
    client.cookies.set("access_token", create_access_token(test_user.id))
    yield client
