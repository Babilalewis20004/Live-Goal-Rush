from collections.abc import AsyncGenerator

import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import competition, match, match_event, player, team  # noqa: F401
from app.services.football_service import FootballService
from app.services.providers import get_provider
from app.services.providers.mock_provider import MockFootballDataProvider

_ASYNC_PREFIX = "postgresql+asyncpg://"
_base_url, _, _dev_db_name = settings.database_url.removeprefix(_ASYNC_PREFIX).rpartition("/")
_TEST_DB_NAME = f"{_dev_db_name}_test"
TEST_DATABASE_URL = f"{_ASYNC_PREFIX}{_base_url}/{_TEST_DB_NAME}"


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
async def client(test_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client for the FastAPI app wired to a fresh test database and
    the mock provider. Does not run the app's startup seeding (the lifespan
    event is not triggered by ASGITransport) -- tests that need pre-seeded
    entities should use the `seeded_client` fixture instead."""
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_provider] = lambda: MockFootballDataProvider()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_client(
    client: AsyncClient, test_engine: AsyncEngine
) -> AsyncGenerator[AsyncClient, None]:
    """Same as `client`, but with the test database pre-populated from the
    mock provider first -- mirrors what the app's startup lifespan does
    against the real database."""
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_local() as session:
        service = FootballService(db=session, provider=MockFootballDataProvider())
        await service.sync_all_competitions_and_fixtures()
    yield client
