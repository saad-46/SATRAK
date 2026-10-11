"""Story 5 — the PostgreSQL audit log is append-only, hash-chained and concurrency-safe (A6)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.security_audit import ACCESS_DENIED, USER_LOGGED_IN, SecurityEvent
from app.db.security_audit_store import SqlSecurityAuditLog
from tests.db.conftest import requires_database

pytestmark = [pytest.mark.integration, requires_database]

RESTRICT_VIOLATION = "23001"


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database)
    yield engine
    await engine.dispose()


@pytest.fixture
def log(engine: AsyncEngine) -> SqlSecurityAuditLog:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return SqlSecurityAuditLog(lambda: maker)


def _event(request_id: str, **kwargs: object) -> SecurityEvent:
    base: dict[str, object] = {
        "event_type": ACCESS_DENIED,
        "outcome": "denied",
        "actor_user_id": uuid.uuid4(),
        "permission": "eo:scene:read",
        "request_id": request_id,
        "details": {"reason": "no_grant", "path": "/x"},
    }
    return SecurityEvent(**{**base, **kwargs})  # type: ignore[arg-type]


async def _sqlstate(engine: AsyncEngine, sql: str) -> str | None:
    from sqlalchemy.exc import DBAPIError

    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    except DBAPIError as exc:
        return getattr(exc.orig, "sqlstate", None)
    return None


async def test_events_round_trip_and_the_chain_verifies(log: SqlSecurityAuditLog) -> None:
    for i in range(5):
        await log.record(
            _event(f"rt-{uuid.uuid4().hex}-{i}", jurisdiction_id=uuid.uuid4(), ip="10.0.0.1")
        )
    report = await log.verify_chain()
    assert report.ok and report.checked >= 5


async def test_concurrent_appends_keep_a_single_linear_chain(
    log: SqlSecurityAuditLog, engine: AsyncEngine
) -> None:
    tag = uuid.uuid4().hex
    await asyncio.gather(
        *(
            log.record(_event(f"{tag}-{i}", event_type=USER_LOGGED_IN, outcome="success"))
            for i in range(25)
        )
    )
    assert (await log.verify_chain()).ok
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT count(*), count(DISTINCT prev_hash) "
                    "FROM audit_event WHERE request_id LIKE :t"
                ),
                {"t": f"{tag}-%"},
            )
        ).one()
    assert rows == (25, 25)  # every event claims a distinct predecessor


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_event SET outcome = 'success'",
        "DELETE FROM audit_event",
        "TRUNCATE audit_event",
    ],
)
async def test_the_table_is_append_only_even_for_its_owner(
    log: SqlSecurityAuditLog, engine: AsyncEngine, sql: str
) -> None:
    await log.record(_event(f"ao-{uuid.uuid4().hex}"))
    assert await _sqlstate(engine, sql) == RESTRICT_VIOLATION


async def test_tampering_by_a_privileged_actor_is_detected(
    log: SqlSecurityAuditLog, engine: AsyncEngine
) -> None:
    request_id = f"tamper-{uuid.uuid4().hex}"
    await log.record(_event(request_id))
    assert (await log.verify_chain()).ok
    async with engine.begin() as conn:  # owner disables the guard, edits, re-enables it
        await conn.execute(
            text("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only_rows")
        )
        await conn.execute(
            text("UPDATE audit_event SET outcome = 'failure' WHERE request_id = :r"),
            {"r": request_id},
        )
        await conn.execute(
            text("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only_rows")
        )
    try:
        report = await log.verify_chain()
        assert (report.ok, report.reason) == (False, "hash mismatch")
    finally:  # leave the shared chain intact for other tests
        async with engine.begin() as conn:
            await conn.execute(
                text("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only_rows")
            )
            await conn.execute(
                text("UPDATE audit_event SET outcome = 'denied' WHERE request_id = :r"),
                {"r": request_id},
            )
            await conn.execute(
                text("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only_rows")
            )
    assert (await log.verify_chain()).ok


async def test_invalid_event_values_are_rejected_by_the_database_too(engine: AsyncEngine) -> None:
    sql = (
        "INSERT INTO audit_event (id, occurred_at, event_type, outcome, prev_hash, hash) "
        "VALUES (gen_random_uuid(), now(), 'user.deleted', 'denied', 'a', 'b')"
    )
    assert await _sqlstate(engine, sql) == "23514"
