"""Story 2 — identity / organization / jurisdiction schema, against real PostGIS (A9, ADR-0011)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.db.conftest import requires_database, run_alembic, sqlstate_of

pytestmark = [pytest.mark.integration, requires_database]

UNIQUE, FK, NOT_NULL, CHECK = "23505", "23503", "23502", "23514"


async def _jurisdiction(
    conn: AsyncConnection, code: str, level: str, parent: uuid.UUID | None = None
) -> uuid.UUID:
    row = await conn.execute(
        text(
            "INSERT INTO jurisdiction (code, name, level, parent_id) "
            "VALUES (:c, :c, :l, :p) RETURNING id"
        ),
        {"c": code, "l": level, "p": parent},
    )
    return row.scalar_one()


async def _user(conn: AsyncConnection, subject: str = "u1") -> uuid.UUID:
    row = await conn.execute(
        text(
            "INSERT INTO user_account (issuer, subject) "
            "VALUES ('https://i.invalid', :s) RETURNING id"
        ),
        {"s": subject},
    )
    return row.scalar_one()


async def _role(conn: AsyncConnection, code: str = "viewer") -> uuid.UUID:
    row = await conn.execute(
        text("INSERT INTO role (code, name) VALUES (:c, :c) RETURNING id"), {"c": code}
    )
    return row.scalar_one()


# --- Migration round-trip --------------------------------------------------------------------
def test_migrations_round_trip_and_have_no_drift(migrated_database: str) -> None:
    for step in (("downgrade", "0001"), ("upgrade", "head"), ("check",)):
        result = run_alembic(*step)
        assert result.returncode == 0, (step, result.stderr[-500:])


async def test_migrations_preserve_data_and_round_trip_to_base(migrated_database: str) -> None:
    """Data written at 0003 survives the RLS migration, in both directions; base is reachable."""
    from sqlalchemy.ext.asyncio import create_async_engine

    assert run_alembic("downgrade", "0003").returncode == 0
    engine = create_async_engine(migrated_database)
    try:
        async with engine.begin() as c:
            nat = await _jurisdiction(c, "IN-mig", "national")
            await c.execute(
                text("INSERT INTO organization (jurisdiction_id, name) VALUES (:j, 'kept')"),
                {"j": nat},
            )
        for step in (("upgrade", "head"), ("downgrade", "0003")):
            result = run_alembic(*step)
            assert result.returncode == 0, (step, result.stderr[-500:])
        async with engine.begin() as c:  # the owner is not bound by RLS at 0003 (no policies)
            count = (
                await c.execute(text("SELECT count(*) FROM organization WHERE name = 'kept'"))
            ).scalar_one()
            assert count == 1
        assert run_alembic("downgrade", "base").returncode == 0
        assert run_alembic("upgrade", "head").returncode == 0
        assert run_alembic("check").returncode == 0
    finally:
        await engine.dispose()


# --- Jurisdiction hierarchy --------------------------------------------------------------------
async def test_hierarchy_accepts_a_valid_chain(conn: AsyncConnection) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    state = await _jurisdiction(conn, "S1", "state", nat)
    city = await _jurisdiction(conn, "C1", "city", state)
    await _jurisdiction(conn, "W1", "ward", city)


async def test_non_national_requires_parent_and_national_forbids_one(conn: AsyncConnection) -> None:
    assert (
        await sqlstate_of(
            conn, "INSERT INTO jurisdiction (code, name, level) VALUES ('X','X','state')"
        )
        == CHECK
    )
    nat = await _jurisdiction(conn, "IN", "national")
    assert (
        await sqlstate_of(
            conn,
            "INSERT INTO jurisdiction (code, name, level, parent_id) "
            "VALUES ('Y','Y','national',:p)",
            p=nat,
        )
        == CHECK
    )


async def test_child_must_be_deeper_than_parent(conn: AsyncConnection) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    state = await _jurisdiction(conn, "S1", "state", nat)
    for level in ("state", "national"):
        assert (
            await sqlstate_of(
                conn,
                "INSERT INTO jurisdiction (code, name, level, parent_id) "
                f"VALUES ('B-{level}','B','{level}',:p)",
                p=state,
            )
            == CHECK
        )


async def test_hierarchy_cycles_are_rejected(conn: AsyncConnection) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    state = await _jurisdiction(conn, "S1", "state", nat)
    city = await _jurisdiction(conn, "C1", "city", state)
    # Re-parent the state under its own descendant.
    assert (
        await sqlstate_of(
            conn,
            "UPDATE jurisdiction SET parent_id = :c, level = 'ward' WHERE id = :s",
            c=city,
            s=state,
        )
        == CHECK
    )
    assert (
        await sqlstate_of(conn, "UPDATE jurisdiction SET parent_id = id WHERE id = :s", s=state)
        == CHECK
    )


async def test_missing_parent_and_duplicate_code(conn: AsyncConnection) -> None:
    assert (
        await sqlstate_of(
            conn,
            "INSERT INTO jurisdiction (code, name, level, parent_id) "
            "VALUES ('Z','Z','state', gen_random_uuid())",
        )
        == FK
    )
    await _jurisdiction(conn, "IN", "national")
    assert (
        await sqlstate_of(
            conn, "INSERT INTO jurisdiction (code, name, level) VALUES ('IN','dup','national')"
        )
        == UNIQUE
    )


async def test_boundary_is_epsg4326_multipolygon(conn: AsyncConnection) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    ok = (
        "UPDATE jurisdiction SET boundary = ST_Multi(ST_GeomFromText("
        "'POLYGON((0 0,1 0,1 1,0 1,0 0))', {srid})) WHERE id = :i"
    )
    assert await sqlstate_of(conn, ok.format(srid=4326), i=nat) is None
    assert await sqlstate_of(conn, ok.format(srid=3857), i=nat) is not None
    assert (
        await sqlstate_of(
            conn,
            "UPDATE jurisdiction SET boundary = ST_GeomFromText('POINT(0 0)', 4326) WHERE id = :i",
            i=nat,
        )
        is not None
    )


# --- Organization (tenant-owned) -----------------------------------------------------------------
async def test_organization_needs_a_jurisdiction_and_unique_name(conn: AsyncConnection) -> None:
    assert (
        await sqlstate_of(conn, "INSERT INTO organization (name) VALUES ('Planning')") == NOT_NULL
    )
    nat = await _jurisdiction(conn, "IN", "national")
    sql = "INSERT INTO organization (jurisdiction_id, name) VALUES (:j, 'Planning')"
    assert await sqlstate_of(conn, sql, j=nat) is None
    assert await sqlstate_of(conn, sql, j=nat) == UNIQUE
    assert await sqlstate_of(conn, sql, j=uuid.uuid4()) == FK


# --- Users, roles, permissions --------------------------------------------------------------------
async def test_new_user_has_no_permissions_and_pending_status(conn: AsyncConnection) -> None:
    uid = await _user(conn)
    status = (
        await conn.execute(text("SELECT status FROM user_account WHERE id = :i"), {"i": uid})
    ).scalar_one()
    assert status == "pending_role_assignment"
    count = (
        await conn.execute(
            text("SELECT count(*) FROM role_assignment WHERE user_id = :i"), {"i": uid}
        )
    ).scalar_one()
    assert count == 0


async def test_user_identity_is_unique_per_issuer_and_subject(conn: AsyncConnection) -> None:
    await _user(conn, "same")
    assert (
        await sqlstate_of(
            conn, "INSERT INTO user_account (issuer, subject) VALUES ('https://i.invalid','same')"
        )
        == UNIQUE
    )
    assert (
        await sqlstate_of(
            conn,
            "INSERT INTO user_account (issuer, subject) VALUES ('https://other.invalid','same')",
        )
        is None
    )
    assert (
        await sqlstate_of(
            conn, "INSERT INTO user_account (issuer, subject, status) VALUES ('i','s2','root')"
        )
        == CHECK
    )


@pytest.mark.parametrize(
    ("code", "ok"),
    [
        ("eo:scene:read", True),
        ("finding:verify", True),
        ("EO:Read", False),
        ("noscope", False),
        ("a:", False),
    ],
)
async def test_permission_code_format(conn: AsyncConnection, code: str, ok: bool) -> None:
    state = await sqlstate_of(conn, "INSERT INTO permission (code) VALUES (:c)", c=code)
    assert (state is None) is ok


# --- Role assignments and cross-jurisdiction grants ----------------------------------------------
async def test_assignment_window_and_grant_rules(conn: AsyncConnection) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    uid, rid = await _user(conn), await _role(conn)
    base = (
        "INSERT INTO role_assignment "
        "(user_id, role_id, jurisdiction_id, kind, reason, valid_from, valid_to) "
        "VALUES (:u, :r, :j, :k, :why, now(), {to})"
    )
    args = {"u": uid, "r": rid, "j": nat}
    ok = base.format(to="NULL")
    assert await sqlstate_of(conn, ok, k="assignment", why=None, **args) is None
    # window must be ordered
    assert (
        await sqlstate_of(
            conn, base.format(to="now() - interval '1 day'"), k="assignment", why=None, **args
        )
        == CHECK
    )
    # cross-jurisdiction grants must expire and carry a reason
    assert await sqlstate_of(conn, ok, k="cross_jurisdiction_grant", why="needed", **args) == CHECK
    soon = base.format(to="now() + interval '1 day'")
    assert await sqlstate_of(conn, soon, k="cross_jurisdiction_grant", why=None, **args) == CHECK
    assert await sqlstate_of(conn, soon, k="cross_jurisdiction_grant", why="  ", **args) == CHECK
    assert (
        await sqlstate_of(conn, soon, k="cross_jurisdiction_grant", why="joint case", **args)
        is None
    )
    assert await sqlstate_of(conn, soon, k="bogus", why="x", **args) == CHECK


async def test_assignment_requires_existing_user_role_and_jurisdiction(
    conn: AsyncConnection,
) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    uid, rid = await _user(conn), await _role(conn)
    sql = "INSERT INTO role_assignment (user_id, role_id, jurisdiction_id) VALUES (:u, :r, :j)"
    assert await sqlstate_of(conn, sql, u=uuid.uuid4(), r=rid, j=nat) == FK
    assert await sqlstate_of(conn, sql, u=uid, r=uuid.uuid4(), j=nat) == FK
    assert await sqlstate_of(conn, sql, u=uid, r=rid, j=uuid.uuid4()) == FK
    assert (
        await sqlstate_of(
            conn, "INSERT INTO role_assignment (user_id, role_id) VALUES (:u, :r)", u=uid, r=rid
        )
        == NOT_NULL
    )


async def test_jurisdiction_with_dependants_cannot_be_deleted(conn: AsyncConnection) -> None:
    nat = await _jurisdiction(conn, "IN", "national")
    await _jurisdiction(conn, "S1", "state", nat)
    assert await sqlstate_of(conn, "DELETE FROM jurisdiction WHERE id = :i", i=nat) == FK
