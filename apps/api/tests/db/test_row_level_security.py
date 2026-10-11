"""Story 7 — PostgreSQL row-level security for tenant-owned tables (ADR-0011, A13)."""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.security_audit import PRIVILEGED_DB_USED, InMemorySecurityAuditLog
from app.db.privileged import privileged_session
from app.db.rls import apply_context, tenant_session, worker_session
from app.db.tenancy import GLOBAL_TABLES, TENANT_TABLES
from tests.db.conftest import (
    ADMIN_ROLE,
    APP_ROLE,
    DATABASE_URL,
    requires_database,
    role_engine,
)
from tests.db_reset import truncate_cascade

pytestmark = [pytest.mark.integration, requires_database]

INSUFFICIENT_PRIVILEGE = "42501"


# Classification lives in app.db.tenancy; a table in neither set fails
# test_every_table_is_classified, forcing a decision (ADR-0011 decision 8).
@dataclass
class Fixture:
    admin: AsyncEngine
    app: AsyncEngine
    j: dict[str, uuid.UUID]
    users: dict[str, uuid.UUID]


@pytest_asyncio.fixture
async def world(migrated_database: str) -> AsyncIterator[Fixture]:
    owner = create_async_engine(migrated_database)
    admin = role_engine(migrated_database, ADMIN_ROLE)
    app = role_engine(migrated_database, APP_ROLE)
    async with owner.begin() as conn:
        await truncate_cascade(
            conn,
            "auth_session, role_assignment, role_permission, role, permission, "
            "user_account, organization, jurisdiction",
        )
    j: dict[str, uuid.UUID] = {}
    users: dict[str, uuid.UUID] = {}
    async with admin.begin() as conn:
        nat = (
            await conn.execute(
                text(
                    "INSERT INTO jurisdiction (code, name, level) "
                    "VALUES ('IN','IN','national') RETURNING id"
                )
            )
        ).scalar_one()
        for name in ("j1", "j2", "j3"):
            j[name] = (
                await conn.execute(
                    text(
                        "INSERT INTO jurisdiction (code, name, level, parent_id) "
                        "VALUES (:c, :c, 'state', :p) RETURNING id"
                    ),
                    {"c": name, "p": nat},
                )
            ).scalar_one()
            await conn.execute(
                text("INSERT INTO organization (jurisdiction_id, name) VALUES (:j, :n)"),
                {"j": j[name], "n": f"org-{name}"},
            )
        role = (
            await conn.execute(text("INSERT INTO role (code, name) VALUES ('r','r') RETURNING id"))
        ).scalar_one()
        for name in ("alice", "bob"):
            users[name] = (
                await conn.execute(
                    text(
                        "INSERT INTO user_account (issuer, subject, status) "
                        "VALUES ('https://i.invalid', :s, 'active') RETURNING id"
                    ),
                    {"s": name},
                )
            ).scalar_one()
        for user, where in (("alice", "j1"), ("alice", "j2"), ("bob", "j3")):
            await conn.execute(
                text(
                    "INSERT INTO role_assignment (user_id, role_id, jurisdiction_id) "
                    "VALUES (:u, :r, :j)"
                ),
                {"u": users[user], "r": role, "j": j[where]},
            )
    try:
        yield Fixture(admin, app, j, users)
    finally:
        await admin.dispose()
        await app.dispose()
        await owner.dispose()


def _sessions(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return lambda: maker


async def _org_names(session: object) -> set[str]:
    rows = await session.execute(text("SELECT name FROM organization"))  # type: ignore[attr-defined]
    return {r.name for r in rows}


async def _sqlstate(coro: object) -> str | None:
    try:
        await coro  # type: ignore[misc]
    except DBAPIError as exc:
        return getattr(exc.orig, "sqlstate", None)
    return None


# --- Policy coverage (the CI check) ---------------------------------------------------------
async def test_every_table_is_classified_and_every_tenant_table_is_protected(
    world: Fixture,
) -> None:
    async with world.app.connect() as conn:
        tables = {
            r.relname: r
            for r in await conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid "
                    "        AND a.attname = 'jurisdiction_id' AND NOT a.attisdropped) AS tenant "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r','p')"
                )
            )
        }
        policies = await conn.execute(
            text("SELECT tablename, cmd FROM pg_policies WHERE schemaname = 'public'")
        )
        by_table: dict[str, set[str]] = {}
        for p in policies:
            by_table.setdefault(p.tablename, set()).add(p.cmd)

    unclassified = set(tables) - TENANT_TABLES - set(GLOBAL_TABLES)
    assert not unclassified, f"classify these tables as tenant-owned or global: {unclassified}"

    # Every table carrying jurisdiction_id is either protected or explicitly global.
    for name, row in tables.items():
        if row.tenant and name not in GLOBAL_TABLES:
            assert name in TENANT_TABLES, f"{name} has jurisdiction_id but is not classified"
    for name in TENANT_TABLES:
        row = tables[name]
        assert row.tenant, f"{name} lost its jurisdiction_id"
        assert row.relrowsecurity and row.relforcerowsecurity, f"{name}: RLS not enabled+forced"
        cmds = by_table.get(name, set())
        assert "ALL" in cmds or {"SELECT", "INSERT", "UPDATE", "DELETE"} <= cmds, name


async def test_jurisdiction_id_is_not_nullable_on_tenant_tables(world: Fixture) -> None:
    async with world.app.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT table_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'jurisdiction_id' "
                "AND table_name = ANY(:t)"
            ),
            {"t": sorted(TENANT_TABLES)},
        )
        assert {(r.table_name, r.is_nullable) for r in rows} == {(t, "NO") for t in TENANT_TABLES}


# --- Default deny and filtering ---------------------------------------------------------------
async def test_without_context_nothing_is_visible_or_writable(world: Fixture) -> None:
    async with world.app.begin() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM organization"))).scalar_one() == 0
        assert (await conn.execute(text("SELECT count(*) FROM role_assignment"))).scalar_one() == 0
    insert = text("INSERT INTO organization (jurisdiction_id, name) VALUES (:j, 'sneaky')")
    async with world.app.connect() as conn:
        assert await _sqlstate(conn.execute(insert, {"j": world.j["j1"]})) == INSUFFICIENT_PRIVILEGE


async def test_context_limits_rows_to_the_permitted_jurisdictions(world: Fixture) -> None:
    sessions = _sessions(world.app)
    cases = [
        ({"j1"}, {"org-j1"}),
        ({"j1", "j2"}, {"org-j1", "org-j2"}),
        ({"j3"}, {"org-j3"}),
        (set(), set()),
    ]
    for allowed, expected in cases:
        ids = {world.j[name] for name in allowed}
        async with tenant_session(sessions, user_id=None, jurisdiction_ids=ids) as session:
            assert await _org_names(session) == expected, allowed


async def test_writes_outside_the_scope_are_rejected_or_affect_nothing(world: Fixture) -> None:
    sessions = _sessions(world.app)
    j1, j2 = world.j["j1"], world.j["j2"]
    async with tenant_session(sessions, user_id=None, jurisdiction_ids={j1}) as session:
        ok = await session.execute(
            text("INSERT INTO organization (jurisdiction_id, name) VALUES (:j, 'new-j1')"),
            {"j": j1},
        )
        assert ok.rowcount == 1
        updated = await session.execute(
            text("UPDATE organization SET name = 'hijacked' WHERE jurisdiction_id = :j"), {"j": j2}
        )
        assert updated.rowcount == 0  # invisible rows are untouchable
    # Neither inserting into, nor moving a row to, a jurisdiction outside the scope.
    for sql in (
        "INSERT INTO organization (jurisdiction_id, name) VALUES (:other, 'x')",
        "UPDATE organization SET jurisdiction_id = :other WHERE name = 'org-j1'",
    ):
        async with tenant_session(sessions, user_id=None, jurisdiction_ids={j1}) as session:
            state = await _sqlstate(session.execute(text(sql), {"other": j2}))
            assert state == INSUFFICIENT_PRIVILEGE, sql
            await session.rollback()
    async with world.admin.connect() as conn:  # ground truth, bypassing RLS
        names = {r.name for r in await conn.execute(text("SELECT name FROM organization"))}
    assert names == {"org-j1", "new-j1", "org-j2", "org-j3"}


async def test_a_user_can_read_only_their_own_assignments_without_a_jurisdiction_context(
    world: Fixture,
) -> None:
    sessions = _sessions(world.app)
    async with tenant_session(
        sessions, user_id=world.users["alice"], jurisdiction_ids=()
    ) as session:
        rows = await session.execute(text("SELECT user_id, jurisdiction_id FROM role_assignment"))
        seen = {(r.user_id, r.jurisdiction_id) for r in rows}
        assert seen == {
            (world.users["alice"], world.j["j1"]),
            (world.users["alice"], world.j["j2"]),
        }
        # Reading one's own assignments grants no write access.
        insert = text(
            "INSERT INTO role_assignment (user_id, role_id, jurisdiction_id) "
            "SELECT :u, id, :j FROM role LIMIT 1"
        )
        state = await _sqlstate(
            session.execute(insert, {"u": world.users["alice"], "j": world.j["j3"]})
        )
        assert state == INSUFFICIENT_PRIVILEGE


async def test_a_malformed_context_fails_closed(world: Fixture) -> None:
    async with world.app.connect() as conn:
        await conn.execute(text("SELECT set_config('app.jurisdiction_ids', 'not-a-uuid', true)"))
        state = await _sqlstate(conn.execute(text("SELECT count(*) FROM organization")))
        assert state is not None  # an error, never "all rows"


# --- Roles ----------------------------------------------------------------------------------
async def test_force_rls_binds_even_the_table_owner(world: Fixture, migrated_database: str) -> None:
    owner = create_async_engine(migrated_database)
    try:
        async with owner.connect() as conn:
            flags = (
                await conn.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                )
            ).one()
            if flags.rolsuper or flags.rolbypassrls:
                pytest.skip("test owner bypasses RLS by privilege; FORCE cannot be observed")
            assert (await conn.execute(text("SELECT count(*) FROM organization"))).scalar_one() == 0
    finally:
        await owner.dispose()


async def test_the_application_role_is_unprivileged(world: Fixture) -> None:
    async with world.app.connect() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
        assert tuple(flags) == (False, False, False, False)
        owned = (
            await conn.execute(
                text("SELECT count(*) FROM pg_tables WHERE tableowner = current_user")
            )
        ).scalar_one()
        assert owned == 0
    statements = [
        "CREATE TABLE sneaky (id int)",
        "ALTER TABLE organization DISABLE ROW LEVEL SECURITY",
        "UPDATE audit_event SET outcome = 'success'",
        "DELETE FROM audit_event",
        "TRUNCATE audit_event",
        "DROP TABLE organization",
        "DELETE FROM jurisdiction",
        "DELETE FROM organization",
    ]
    for sql in statements:
        async with world.app.connect() as conn:
            assert await _sqlstate(conn.execute(text(sql))) == INSUFFICIENT_PRIVILEGE, sql


async def test_the_maintenance_role_is_the_only_one_that_bypasses(world: Fixture) -> None:
    async with world.admin.connect() as conn:
        bypass = (
            await conn.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar_one()
        assert bypass is True
        assert (await conn.execute(text("SELECT count(*) FROM organization"))).scalar_one() == 3


# --- Pools never leak context -------------------------------------------------------------------
async def test_a_reused_connection_carries_no_context_between_requests(
    world: Fixture, migrated_database: str
) -> None:
    # A single-connection pool forces every request onto the same physical connection.
    pooled = role_engine(migrated_database, APP_ROLE, pool_size=1, max_overflow=0)
    sessions = _sessions(pooled)
    j1 = world.j["j1"]

    async def pid_and_visible(context: set[uuid.UUID] | None) -> tuple[int, set[str], str | None]:
        if context is None:
            async with sessions()() as session, session.begin():
                pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                guc = (
                    await session.execute(
                        text("SELECT current_setting('app.jurisdiction_ids', true)")
                    )
                ).scalar_one()
                return pid, await _org_names(session), guc
        async with tenant_session(sessions, user_id=None, jurisdiction_ids=context) as session:
            pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            return pid, await _org_names(session), "(set)"

    try:
        pid_a, seen_a, _ = await pid_and_visible({j1})
        pid_b, seen_b, guc_b = await pid_and_visible(None)
        assert pid_a == pid_b  # really the same connection
        assert seen_a == {"org-j1"} and seen_b == set()
        assert guc_b in (None, "")

        # After an exception inside the transaction.
        with pytest.raises(RuntimeError):
            async with tenant_session(sessions, user_id=None, jurisdiction_ids={j1}) as session:
                assert await _org_names(session) == {"org-j1"}
                raise RuntimeError("boom")
        assert (await pid_and_visible(None))[1:] == (set(), guc_b)

        # After an explicit rollback and after the task is cancelled mid-transaction.
        async with sessions()() as session, session.begin():
            await apply_context(session, user_id=None, jurisdiction_ids={j1})
            await session.rollback()
        assert (await pid_and_visible(None))[1] == set()

        async def hang() -> None:
            async with tenant_session(sessions, user_id=None, jurisdiction_ids={j1}) as session:
                await session.execute(text("SELECT pg_sleep(30)"))

        task = asyncio.create_task(hang())
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await pid_and_visible(None))[1] == set()
    finally:
        await pooled.dispose()


async def test_concurrent_requests_each_see_only_their_own_jurisdiction(
    world: Fixture, migrated_database: str
) -> None:
    pooled = role_engine(migrated_database, APP_ROLE)
    sessions = _sessions(pooled)
    names = ["j1", "j2", "j3", None]
    rng = random.Random(7)

    async def request(which: str | None) -> tuple[str | None, set[str]]:
        ids = {world.j[which]} if which else set()
        async with tenant_session(sessions, user_id=None, jurisdiction_ids=ids) as session:
            await session.execute(text("SELECT pg_sleep(:s)"), {"s": rng.random() / 20})
            return which, await _org_names(session)

    try:
        results = await asyncio.gather(*(request(rng.choice(names)) for _ in range(120)))
    finally:
        await pooled.dispose()
    for which, seen in results:
        assert seen == ({f"org-{which}"} if which else set()), which


async def test_the_context_can_only_be_set_inside_a_transaction(world: Fixture) -> None:
    maker = async_sessionmaker(world.app, expire_on_commit=False)
    async with maker() as session:
        with pytest.raises(RuntimeError, match="inside a transaction"):
            await apply_context(session, user_id=None, jurisdiction_ids=())


# --- Workers and privileged access --------------------------------------------------------------
async def test_workers_must_declare_a_scope_and_get_only_that_scope(world: Fixture) -> None:
    sessions = _sessions(world.app)
    with pytest.raises(ValueError, match="at least one jurisdiction"):
        async with worker_session(sessions, job="nightly", jurisdiction_ids=[]):
            pass
    async with worker_session(sessions, job="nightly", jurisdiction_ids=[world.j["j2"]]) as s:
        assert await _org_names(s) == {"org-j2"}


async def test_privileged_access_is_audited_first_and_fails_closed(world: Fixture) -> None:
    audit = InMemorySecurityAuditLog()
    sessions = _sessions(world.admin)
    async with privileged_session(
        sessions, audit=audit, operator="ops-1", reason="repair org names"
    ) as session:
        assert len(await _org_names(session)) == 3  # bypasses RLS
    (event,) = audit.of_type(PRIVILEGED_DB_USED)
    assert event.details == {"operator": "ops-1", "reason": "repair org names"}

    audit.fail = True
    entered = False
    with pytest.raises(RuntimeError):
        async with privileged_session(sessions, audit=audit, operator="ops-1", reason="again"):
            entered = True
    assert entered is False
    with pytest.raises(ValueError):
        async with privileged_session(sessions, audit=audit, operator="ops-1", reason="  "):
            pass


def test_the_web_layer_never_imports_the_privileged_module() -> None:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    offenders = [
        str(path.relative_to(root))
        for folder in ("api", "contexts")
        for path in (root / folder).rglob("*.py")
        if "app.db.privileged" in path.read_text()
    ]
    assert offenders == []


def test_database_url_is_configured_for_this_module() -> None:
    assert DATABASE_URL is not None


# --- Fixtures really run as the intended roles ------------------------------------------------
async def test_test_engines_run_as_the_intended_database_roles(world: Fixture) -> None:
    for engine, expected in ((world.app, APP_ROLE), (world.admin, ADMIN_ROLE)):
        for _ in range(3):  # repeated checkouts: a lost SET ROLE would show up as the owner
            async with engine.connect() as conn:
                user = (await conn.execute(text("SELECT current_user"))).scalar_one()
                assert user == expected


async def test_the_access_store_reads_through_the_application_role(world: Fixture) -> None:
    sessions = _sessions(world.app)
    async with sessions()() as session, session.begin():
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == APP_ROLE


# --- Session pruning ---------------------------------------------------------------------------
async def test_session_pruning_removes_only_long_expired_rows_and_is_audited(
    world: Fixture,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.maintenance import prune_auth_sessions

    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    async with world.admin.begin() as conn:
        for key, expires in (
            ("old", now - timedelta(days=40)),
            ("recent", now - timedelta(days=5)),
            ("live", now + timedelta(minutes=10)),
        ):
            await conn.execute(
                text(
                    "INSERT INTO auth_session "
                    "(issuer, session_key, user_id, expires_at, revoked_at) "
                    "VALUES ('https://i.invalid', :k, :u, :e, :e)"
                ),
                {"k": key, "u": world.users["alice"], "e": expires},
            )
    audit = InMemorySecurityAuditLog()
    removed = await prune_auth_sessions(
        _sessions(world.admin), audit=audit, operator="job", now=now, retention_days=30
    )
    assert removed == 1
    assert len(audit.of_type(PRIVILEGED_DB_USED)) == 1
    async with world.admin.connect() as conn:
        left = {
            r.session_key for r in await conn.execute(text("SELECT session_key FROM auth_session"))
        }
    assert left == {"recent", "live"}
    with pytest.raises(ValueError):
        await prune_auth_sessions(
            _sessions(world.admin), audit=audit, operator="job", now=now, retention_days=0
        )
    async with world.app.connect() as conn:  # the API role cannot prune
        state = await _sqlstate(conn.execute(text("DELETE FROM auth_session")))
        assert state == INSUFFICIENT_PRIVILEGE


# --- Startup validation of the application role -----------------------------------------------
async def test_the_application_role_passes_the_startup_check(world: Fixture) -> None:
    from app.db.role_check import assert_safe_application_role

    report = await assert_safe_application_role(world.app)
    assert report.role == APP_ROLE and report.safe


async def test_unsafe_roles_are_rejected_at_startup(world: Fixture, migrated_database: str) -> None:
    from app.db.role_check import UnsafeDatabaseRoleError, assert_safe_application_role

    # The maintenance role bypasses RLS and must never serve the API.
    with pytest.raises(UnsafeDatabaseRoleError, match="BYPASSRLS"):
        await assert_safe_application_role(world.admin)
    # A table owner could disable RLS.
    owner = create_async_engine(migrated_database)
    try:
        with pytest.raises(UnsafeDatabaseRoleError, match="owns tables"):
            await assert_safe_application_role(owner)
    finally:
        await owner.dispose()


async def test_a_jurisdiction_table_without_forced_rls_is_rejected(
    world: Fixture, migrated_database: str
) -> None:
    from app.db.role_check import UnsafeDatabaseRoleError, assert_safe_application_role

    owner = create_async_engine(migrated_database)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("CREATE TABLE leaky_tenant_data (jurisdiction_id uuid)"))
            await conn.execute(text("GRANT SELECT ON leaky_tenant_data TO satrak_app"))
        with pytest.raises(UnsafeDatabaseRoleError, match="leaky_tenant_data"):
            await assert_safe_application_role(world.app)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS leaky_tenant_data"))
        await owner.dispose()


@pytest.mark.parametrize(
    ("ddl", "table", "expected"),
    [
        ("CREATE TABLE scratch_unlisted (id int)", "scratch_unlisted", "neither as tenant"),
        (
            "CREATE SCHEMA scratch_schema; CREATE TABLE scratch_schema.t (id int)",
            "scratch_schema.t",
            "neither as tenant",
        ),
        (
            "CREATE TABLE scratch_open (jurisdiction_id uuid NOT NULL);"
            " ALTER TABLE scratch_open ENABLE ROW LEVEL SECURITY",  # enabled but not forced
            "scratch_open",
            "enabled and forced",
        ),
    ],
    ids=["unclassified-no-column", "other-schema", "rls-not-forced"],
)
async def test_unclassified_or_unprotected_tables_cannot_pass_startup(
    world: Fixture, migrated_database: str, ddl: str, table: str, expected: str
) -> None:
    from app.db.role_check import UnsafeDatabaseRoleError, assert_safe_application_role

    owner = create_async_engine(migrated_database)
    try:
        async with owner.begin() as conn:
            for statement in ddl.split(";"):
                await conn.execute(text(statement))
            if "." in table:
                await conn.execute(text("GRANT USAGE ON SCHEMA scratch_schema TO satrak_app"))
        with pytest.raises(UnsafeDatabaseRoleError, match=expected) as caught:
            await assert_safe_application_role(world.app)
        assert table.split(".")[-1] in str(caught.value) or "scratch" in str(caught.value)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS scratch_unlisted, scratch_open"))
            await conn.execute(text("DROP SCHEMA IF EXISTS scratch_schema CASCADE"))
        await owner.dispose()


async def test_a_declared_tenant_table_must_have_a_policy_and_a_non_null_column(
    world: Fixture, migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import role_check
    from app.db.role_check import UnsafeDatabaseRoleError, assert_safe_application_role

    owner = create_async_engine(migrated_database)
    monkeypatch.setattr(
        role_check, "TENANT_TABLES", TENANT_TABLES | {"scratch_tenant", "scratch_missing"}
    )
    try:
        async with owner.begin() as conn:
            await conn.execute(text("CREATE TABLE scratch_tenant (jurisdiction_id uuid)"))
            await conn.execute(text("ALTER TABLE scratch_tenant ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text("ALTER TABLE scratch_tenant FORCE ROW LEVEL SECURITY"))
        with pytest.raises(UnsafeDatabaseRoleError) as caught:
            await assert_safe_application_role(world.app)
        message = str(caught.value)
        assert "without a policy" in message and "scratch_tenant" in message
        assert "NOT NULL jurisdiction_id" in message and "scratch_missing" in message
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS scratch_tenant"))
        await owner.dispose()
