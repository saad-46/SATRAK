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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

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


APP_ROLE = "satrak_app"
ADMIN_ROLE = "satrak_admin"


def role_engine(url: str, role: str, **engine_args: object) -> AsyncEngine:
    """An engine whose every connection runs ``SET ROLE <role>`` (session level, so the pool's
    rollback-on-return does not undo it). Stands in for logging in as that role."""
    engine = create_async_engine(url, **engine_args)  # type: ignore[arg-type]

    @event.listens_for(engine.sync_engine, "connect")
    def _set_role(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute(f"SET ROLE {role}")
        cursor.close()
        # Commit, or the pool's rollback-on-return would silently undo the SET ROLE.
        dbapi_connection.commit()  # type: ignore[attr-defined]

    return engine


def _roles_ready(url: str) -> bool:
    """The suite needs the roles from infra/db/roles.sql, usable by the test owner via SET ROLE."""
    import asyncio

    async def check() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as c:
                for role in (APP_ROLE, ADMIN_ROLE):
                    await c.execute(text(f"SET ROLE {role}"))
                    await c.execute(text("RESET ROLE"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    # A fresh thread gives asyncio.run its own loop even when called under a running one.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, check()).result()


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Rebuild the schema from migrations once per run and return the URL."""
    if DATABASE_URL is None:
        pytest.skip("SATRAK_TEST_DATABASE_URL is not set")
    if not _roles_ready(DATABASE_URL):
        pytest.skip(
            "roles satrak_app/satrak_admin are missing or not grantable to the test user: run "
            "infra/db/roles.sql as a superuser, then GRANT both roles to the test user"
        )
    for step in (("downgrade", "base"), ("upgrade", "head")):
        result = run_alembic(*step)
        assert result.returncode == 0, result.stderr
    return DATABASE_URL


@pytest_asyncio.fixture
async def conn(migrated_database: str) -> AsyncIterator[AsyncConnection]:
    """A maintenance-role connection inside a transaction that is always rolled back."""
    # The maintenance role bypasses RLS, so schema tests can seed any jurisdiction's rows.
    engine = role_engine(migrated_database, ADMIN_ROLE)
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
