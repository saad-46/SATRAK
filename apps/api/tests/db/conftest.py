"""Fixtures for tests that need a real PostgreSQL/PostGIS database.

Set ``SATRAK_TEST_DATABASE_URL`` (asyncpg URL for a disposable database whose role may create
tables) to run them; they are skipped otherwise. The schema is rebuilt with Alembic
(downgrade base, upgrade head) so the tests exercise the real migrations.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

API_DIR = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("SATRAK_TEST_DATABASE_URL")

requires_database = pytest.mark.skipif(
    DATABASE_URL is None, reason="SATRAK_TEST_DATABASE_URL is not set"
)


def run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    assert DATABASE_URL is not None
    env = {**os.environ, "SATRAK_API_DATABASE_URL": DATABASE_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Rebuild the schema from migrations once per run and return the URL."""
    if DATABASE_URL is None:
        pytest.skip("SATRAK_TEST_DATABASE_URL is not set")
    for step in (("downgrade", "base"), ("upgrade", "head")):
        result = run_alembic(*step)
        assert result.returncode == 0, result.stderr
    return DATABASE_URL


@pytest_asyncio.fixture
async def conn(migrated_database: str) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back."""
    engine = create_async_engine(migrated_database)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


async def sqlstate_of(conn: AsyncConnection, sql: str, **params: object) -> str | None:
    """Run ``sql`` in a savepoint; return the SQLSTATE it fails with (None if it succeeds)."""
    try:
        async with conn.begin_nested():
            await conn.execute(text(sql), params)
    except DBAPIError as exc:
        return getattr(exc.orig, "sqlstate", None)
    return None
