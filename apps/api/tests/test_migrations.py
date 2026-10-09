"""Migration safety (Phase 7 §8, §39): the migration chain builds a database identical to the models, upgrades
an existing database without losing data, and the newest revision is reversible."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata

from tests.conftest import _base_url

API_DIR = Path(__file__).resolve().parent.parent
PREVIOUS_HEAD = "a7c3d9e1b402"  # the last revision before Phase 7


def _admin_dsn() -> str:
    return f"postgresql://{_base_url}/postgres"


async def _create_db(name: str) -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_db(name: str) -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


@pytest.fixture
def scratch_db():
    name = f"migtest_{uuid.uuid4().hex[:10]}"
    asyncio.run(_create_db(name))
    try:
        yield name
    finally:
        asyncio.run(_drop_db(name))


def alembic(db_name: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"postgresql+asyncpg://{_base_url}/{db_name}", "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    return result


async def _fetch(db_name: str, query: str, *args):
    conn = await asyncpg.connect(f"postgresql://{_base_url}/{db_name}")
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


async def _execute(db_name: str, query: str, *args):
    conn = await asyncpg.connect(f"postgresql://{_base_url}/{db_name}")
    try:
        return await conn.execute(query, *args)
    finally:
        await conn.close()


def test_there_is_exactly_one_migration_head():
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))
    assert len(script.get_heads()) == 1, "two migrations branch from the same parent; merge them"


def test_every_migration_has_a_downgrade():
    versions = (API_DIR / "alembic" / "versions").glob("*.py")
    missing = [p.name for p in versions if "def downgrade" not in p.read_text(encoding="utf8")]
    assert missing == []


def test_a_fresh_database_reaches_head_and_matches_the_models(scratch_db):
    alembic(scratch_db, "upgrade", "head")
    rows = asyncio.run(_fetch(scratch_db, "SELECT version_num FROM alembic_version"))
    script = ScriptDirectory.from_config(Config(str(API_DIR / "alembic.ini")))
    assert [r["version_num"] for r in rows] == script.get_heads()

    tables = {r["tablename"] for r in asyncio.run(_fetch(scratch_db, "SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
    from app.db.base import Base
    import app.models  # noqa: F401  (register every table)

    missing = set(Base.metadata.tables) - tables
    assert missing == set(), f"models define tables the migrations never create: {sorted(missing)}"


def test_the_migrated_schema_has_no_drift_from_the_models(scratch_db):
    """What `alembic revision --autogenerate` would still want to change after upgrading to head. Anything listed
    here means a model was edited without a migration (or vice versa)."""
    alembic(scratch_db, "upgrade", "head")
    import app.models  # noqa: F401
    from app.db.base import Base

    from sqlalchemy.ext.asyncio import create_async_engine

    async def diff_models() -> list:
        engine = create_async_engine(f"postgresql+asyncpg://{_base_url}/{scratch_db}")
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: compare_metadata(
                        MigrationContext.configure(sync_conn, opts={"compare_type": False, "compare_server_default": False}),
                        Base.metadata,
                    )
                )
        finally:
            await engine.dispose()

    diff = asyncio.run(diff_models())
    significant = [d for d in diff if d[0] in ("add_table", "remove_table", "add_column", "remove_column")]
    assert significant == [], significant


def test_upgrading_an_existing_database_keeps_its_data(scratch_db):
    alembic(scratch_db, "upgrade", PREVIOUS_HEAD)
    asyncio.run(
        _execute(
            scratch_db,
            "INSERT INTO users (email, hashed_password, display_name, is_active, role, profile_public) "
            "VALUES ('keep@example.com', 'hash', 'Keeper', true, 'USER', false)",
        )
    )
    alembic(scratch_db, "upgrade", "head")
    row = asyncio.run(_fetch(scratch_db, "SELECT email, display_name, deleted_at FROM users"))[0]
    assert (row["email"], row["display_name"], row["deleted_at"]) == ("keep@example.com", "Keeper", None)
    cols = {r["column_name"] for r in asyncio.run(_fetch(scratch_db, "SELECT column_name FROM information_schema.columns WHERE table_name='subscriptions'"))}
    assert "last_event_at" in cols
    # the case-insensitive lookup now has an index to use
    idx = asyncio.run(_fetch(scratch_db, "SELECT indexdef FROM pg_indexes WHERE indexname='ix_users_email_lower'"))
    assert idx and "lower" in idx[0]["indexdef"]


def test_the_newest_migration_is_reversible_and_repeatable(scratch_db):
    alembic(scratch_db, "upgrade", "head")
    alembic(scratch_db, "downgrade", PREVIOUS_HEAD)
    tables = {r["tablename"] for r in asyncio.run(_fetch(scratch_db, "SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
    assert "failed_jobs" not in tables and "audit_log" not in tables
    alembic(scratch_db, "upgrade", "head")
    tables = {r["tablename"] for r in asyncio.run(_fetch(scratch_db, "SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
    assert {"failed_jobs", "audit_log"} <= tables


def test_upgrading_twice_is_a_no_op(scratch_db):
    alembic(scratch_db, "upgrade", "head")
    result = alembic(scratch_db, "upgrade", "head")
    assert "Running upgrade" not in result.stderr + result.stdout
