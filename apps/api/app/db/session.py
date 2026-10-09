from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# asyncpg waits 60 s to connect by default: with the database black-holed (a network partition, a stopped host) every request
# would hang for a minute holding a worker slot. Fail in seconds instead so the API can answer 503 and recover quickly.
_connect_timeout_seconds = 5
_command_timeout_seconds = 30
_server_settings = {"application_name": settings.service_name}
if settings.db_statement_timeout_ms > 0:
    _server_settings["statement_timeout"] = str(settings.db_statement_timeout_ms)

CONNECT_ARGS = {"server_settings": _server_settings, "timeout": _connect_timeout_seconds, "command_timeout": _command_timeout_seconds}

# Bounded pool (Phase 7): a burst queues for `pool_timeout` and then fails fast (the API turns that into a 503
# with Retry-After) instead of opening connections without limit until Postgres refuses everyone.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
    connect_args=CONNECT_ARGS,
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped database session."""
    async with AsyncSessionLocal() as session:
        yield session
