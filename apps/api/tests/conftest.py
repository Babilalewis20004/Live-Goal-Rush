from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from fakeredis import aioredis as fakeredis_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_storage_dep
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
    lineup,
    match,
    match_event,
    notification,
    player,
    session as session_model,
    standing,
    statistics,
    team,
    user,
)
from app.models.user import User
from app.services.football_service import FootballService
from app.services.providers import get_provider
from tests.fakes.mock_provider import MockFootballDataProvider
from app.services.storage import MemoryStorage

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


_SCHEMA_READY = False
"""The schema is (re)built once per pytest *session*; each test then starts from empty tables."""


@pytest_asyncio.fixture
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """A fresh engine per test, bound to that test's own event loop --
    pytest-asyncio gives every test function a new loop, and asyncpg
    connections can't be reused across loops, so the engine (and its
    connection pool) must not outlive a single test either.

    Every test sees an empty database with identity counters reset (so ids
    start at 1, as when the schema was rebuilt per test). Rebuilding the whole
    schema -- tables plus trigram indexes -- for each of ~700 tests cost 3-8 s
    apiece; creating it once and emptying the tables is the same isolation for a fraction of that."""
    global _SCHEMA_READY
    await _ensure_test_database_exists()
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        if not _SCHEMA_READY:
            # Phase 4's trigram search indexes need this extension (the
            # migration creates it for real databases).
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            _SCHEMA_READY = True
        else:
            # DELETE (children first) + reset the id sequences. TRUNCATE gives the same result but allocates
            # fresh files for every table and index, which costs ~1 s of fsync per test on Docker/Windows;
            # this takes ~0.15 s. `synchronous_commit` is off for this cleanup transaction only.
            await conn.execute(text("SET LOCAL synchronous_commit = off"))
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(text(f'DELETE FROM "{table.name}"'))
            for table in Base.metadata.sorted_tables:
                id_column = table.c.get("id")
                if id_column is not None and id_column.primary_key and id_column.autoincrement is not False:
                    await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), 1, false)"))
    yield engine
    await engine.dispose()


@pytest.fixture
def fake_redis_server():
    """The in-memory server behind `fake_redis`, for tests that also need a
    *sync* client (the Celery worker's) looking at the same data."""
    import fakeredis

    return fakeredis.FakeServer()


@pytest_asyncio.fixture
async def fake_redis(fake_redis_server) -> AsyncGenerator[RedisService, None]:
    """An isolated in-memory Redis (via fakeredis) per test -- exercises
    the real cache-aside code path (JSON encode/decode, TTLs, pub/sub)
    without requiring a real Redis server for the test suite."""
    client = fakeredis_aioredis.FakeRedis(server=fake_redis_server, decode_responses=True)
    yield RedisService(settings.redis_url, client=client)
    await client.aclose()


@pytest.fixture
def memory_storage() -> MemoryStorage:
    """Uploaded media goes to memory in tests -- never to disk or the network."""
    return MemoryStorage()


@pytest_asyncio.fixture
async def client(
    test_engine: AsyncEngine, fake_redis: RedisService, memory_storage: MemoryStorage
) -> AsyncGenerator[AsyncClient, None]:
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
    app.dependency_overrides[get_storage_dep] = lambda: memory_storage
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


# -- Phase 4 fixtures ----------------------------------------------------------


@pytest_asyncio.fixture
async def get_match_id(test_engine: AsyncEngine):
    """`await get_match_id("ucl-1")` -> the internal id of the match the mock
    provider knows as "ucl-1" (API paths use internal ids)."""
    from sqlalchemy import select

    from app.models.match import Match

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _lookup(provider_id: str) -> int:
        async with session_local() as session:
            return (await session.execute(select(Match.id).where(Match.provider_id == provider_id))).scalar_one()

    return _lookup


@pytest_asyncio.fixture
async def phase4_client(seeded_client: AsyncClient, test_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """`seeded_client` plus what the worker stores for every non-historical
    match: lineups, team statistics and player statistics (`sync_match_extras`
    -- the same call the live sync loop makes)."""
    from sqlalchemy import select

    from app.models.match import Match
    from app.services.match_centre_service import MatchCentreService

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    provider = MockFootballDataProvider()
    async with session_local() as session:
        football = FootballService(db=session, provider=provider)
        centre = MatchCentreService(session, provider, football=football)
        matches = (
            (await session.execute(select(Match).where(~Match.provider_id.startswith("hist-")))).scalars().all()
        )
        for match in matches:
            await centre.sync_match_extras(match)
        await session.commit()
    yield seeded_client


@pytest_asyncio.fixture
async def session_factory(test_engine: AsyncEngine):
    """An `async_sessionmaker` on the per-test database, for tests that
    drive service-layer code (sync methods) directly."""
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


# -- Discovery (Phase 5) fixtures ------------------------------------------------


@pytest_asyncio.fixture
async def make_user(test_engine: AsyncEngine):
    """`user, headers = await make_user("ed@example.com", UserRole.EDITOR)` --
    a persisted user plus `Authorization: Bearer` headers for them. Header
    auth (rather than the shared client's cookie jar) lets one test act as
    several different people."""
    from app.models.enums import UserRole

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _make(email: str, role: "UserRole" = UserRole.USER):
        async with session_local() as session:
            instance = User(
                email=email,
                hashed_password=hash_password("Sup3rSecret!"),
                display_name=email.split("@")[0].title(),
                role=role,
            )
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
        return instance, {"Authorization": f"Bearer {create_access_token(instance.id)}"}

    return _make


@pytest_asyncio.fixture
async def lookup(test_engine: AsyncEngine):
    """`await lookup(Team, "Arsenal")` -> that row's id."""
    from sqlalchemy import select

    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def _lookup(model, name: str) -> int:
        async with session_local() as session:
            return (await session.execute(select(model.id).where(model.name == name))).scalar_one()

    return _lookup


@pytest_asyncio.fixture
async def publish_article(client: AsyncClient):
    """`article = await publish_article(headers, title=..., team_ids=[...])`:
    creates and publishes through the real editor API."""

    async def _publish(headers: dict, title: str = "Match preview", publish: bool = True, **fields):
        body = {"title": title, "content": f"<p>{title} body text.</p>", **fields}
        resp = await client.post("/api/v1/editor/articles", json=body, headers=headers)
        assert resp.status_code == 201, resp.text
        article = resp.json()
        if publish:
            resp = await client.post(f"/api/v1/editor/articles/{article['id']}/publish", headers=headers)
            assert resp.status_code == 200, resp.text
            article = resp.json()
        return article

    return _publish


# -- Phase 6 fixtures ----------------------------------------------------------------


@pytest.fixture
def make_image():
    """`make_image("PNG", (200, 150))` -> bytes of a real image of that format/size."""
    import io

    from PIL import Image

    def _make(fmt: str = "PNG", size: tuple[int, int] = (200, 150), mode: str = "RGB", **save_kwargs) -> bytes:
        img = Image.new(mode, size, (30, 140, 90) if mode == "RGB" else (30, 140, 90, 128))
        out = io.BytesIO()
        img.save(out, format=fmt, **save_kwargs)
        return out.getvalue()

    return _make


@pytest_asyncio.fixture
async def upload(client: AsyncClient, make_image):
    """`media = await upload(headers, ...)`: uploads through the real endpoint."""

    async def _upload(headers: dict, data: bytes | None = None, filename: str = "photo.png", content_type: str = "image/png", **form):
        data = data if data is not None else make_image()
        resp = await client.post(
            "/api/v1/editor/media", headers=headers, files={"file": (filename, data, content_type)}, data=form
        )
        return resp

    return _upload
