"""Database guarantees of the compliance workflow (migration 0005).

These run against real PostgreSQL/PostGIS: forced row-level security, least-privilege grants,
append-only history, same-jurisdiction links, and the ADR-0014 release gate enforced by triggers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine

from app.db.rls import tenant_session
from app.db.tenancy import TENANT_TABLES
from tests.db.conftest import (
    ADMIN_ROLE,
    APP_ROLE,
    requires_database,
    role_engine,
    sqlstate_of,
)
from tests.db_reset import APPEND_ONLY, truncate_cascade

pytestmark = [pytest.mark.integration, requires_database]

DAY = date(2026, 1, 1)
RESTRICT_VIOLATION = "23001"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
INSUFFICIENT_PRIVILEGE = "42501"

_RING = "POLYGON(({0} {1}, {2} {1}, {2} {3}, {0} {3}, {0} {1}))"
SQUARE = f"ST_GeomFromText('{_RING.format(77.0, 12.0, 77.001, 12.001)}', 4326)"
INSIDE = f"ST_GeomFromText('{_RING.format(77.0002, 12.0002, 77.0004, 12.0004)}', 4326)"
BOWTIE = "ST_GeomFromText('POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))', 4326)"
RESET_TABLES = (
    "role_assignment, role_permission, role, permission, user_account, organization, jurisdiction"
)


class Raw(str):
    """A SQL expression (never client input) used as a column value."""


def _insert_sql(table: str, values: dict[str, object]) -> tuple[str, dict[str, object]]:
    columns = ", ".join(values)
    marks = ", ".join(v if isinstance(v, Raw) else f":{k}" for k, v in values.items())
    params = {k: v for k, v in values.items() if not isinstance(v, Raw)}
    return f"INSERT INTO {table} ({columns}) VALUES ({marks})", params


async def _state(conn: AsyncConnection, sql: str, **params: object) -> str:
    return (await sqlstate_of(conn, sql, **params)) or "ok"


@dataclass
class World:
    conn: AsyncConnection
    j1: uuid.UUID
    j2: uuid.UUID
    user: uuid.UUID
    parcel1: uuid.UUID
    parcel2: uuid.UUID

    async def add(self, table: str, **values: object) -> uuid.UUID:
        sql, params = _insert_sql(table, values)
        return (await self.conn.execute(text(sql + " RETURNING id"), params)).scalar_one()

    async def try_add(self, table: str, **values: object) -> str:
        sql, params = _insert_sql(table, values)
        return await _state(self.conn, sql, **params)

    def _audit(self) -> dict[str, object]:
        return {"created_by": self.user, "updated_by": self.user}

    def candidate_values(self, jurisdiction: uuid.UUID, **over: object) -> dict[str, object]:
        values: dict[str, object] = {
            "jurisdiction_id": jurisdiction,
            "source_type": "manual_report",
            "observed_on": DAY,
            "change_type": "new_structure",
            "footprint": Raw(INSIDE),
            "footprint_area_sq_m": 100,
            **self._audit(),
        }
        values.update(over)
        return values

    async def candidate(
        self, jurisdiction: uuid.UUID, parcel: uuid.UUID | None = None
    ) -> uuid.UUID:
        return await self.add(
            "construction_change_candidate", **self.candidate_values(jurisdiction, parcel_id=parcel)
        )

    def review_values(
        self, candidate: uuid.UUID, jurisdiction: uuid.UUID, status: str
    ) -> dict[str, object]:
        decision = {
            "confirmed": "confirm",
            "rejected": "reject",
            "needs_evidence": "request_evidence",
        }
        return {
            "candidate_id": candidate,
            "jurisdiction_id": jurisdiction,
            "reviewer_id": self.user,
            "decision": decision[status],
            "resulting_status": status,
            "justification": "reviewed by the officer",
        }

    async def review(
        self, candidate: uuid.UUID, jurisdiction: uuid.UUID, status: str, *, apply: bool = True
    ) -> None:
        await self.add("candidate_review", **self.review_values(candidate, jurisdiction, status))
        if apply:  # the service records the review and moves the candidate in one transaction
            await self.conn.execute(
                text("UPDATE construction_change_candidate SET status = :s WHERE id = :c"),
                {"s": status, "c": candidate},
            )

    async def set_status(self, candidate: uuid.UUID, status: str) -> str:
        return await _state(
            self.conn,
            "UPDATE construction_change_candidate SET status = :s WHERE id = :c",
            s=status,
            c=candidate,
        )

    async def evaluation(self, candidate: uuid.UUID, jurisdiction: uuid.UUID) -> uuid.UUID:
        return await self.add(
            "candidate_evaluation",
            candidate_id=candidate,
            jurisdiction_id=jurisdiction,
            evaluated_by=self.user,
            classification="unpermitted_construction",
            severity="high",
            failed_rules=Raw("'[]'::jsonb"),
            result=Raw("'{}'::jsonb"),
        )

    def case_values(
        self, candidate: uuid.UUID, evaluation: uuid.UUID, jurisdiction: uuid.UUID
    ) -> dict[str, object]:
        return {
            "jurisdiction_id": jurisdiction,
            "candidate_id": candidate,
            "evaluation_id": evaluation,
            "source_type": "manual_report",
            "severity": "high",
            "priority_score": 70,
            "status": "created",
            "opened_by": self.user,
            **self._audit(),
        }

    async def try_case(
        self, candidate: uuid.UUID, evaluation: uuid.UUID, jurisdiction: uuid.UUID
    ) -> str:
        return await self.try_add(
            "inspection_case", **self.case_values(candidate, evaluation, jurisdiction)
        )

    async def open_case(self) -> tuple[uuid.UUID, uuid.UUID]:
        candidate = await self.candidate(self.j1)
        await self.review(candidate, self.j1, "confirmed")
        evaluation = await self.evaluation(candidate, self.j1)
        case = await self.add("inspection_case", **self.case_values(candidate, evaluation, self.j1))
        return candidate, case


@pytest_asyncio.fixture
async def w(conn: AsyncConnection) -> AsyncIterator[World]:
    async def one(sql: str, **p: object) -> uuid.UUID:
        return (await conn.execute(text(sql), p)).scalar_one()

    nat = await one(
        "INSERT INTO jurisdiction (code,name,level) VALUES ('X','X','national') RETURNING id"
    )
    state = (
        "INSERT INTO jurisdiction (code,name,level,parent_id)"
        " VALUES (:c,:c,'state',:p) RETURNING id"
    )
    j1 = await one(state, c="c1", p=nat)
    j2 = await one(state, c="c2", p=nat)
    user = await one(
        "INSERT INTO user_account (issuer,subject,status)"
        " VALUES ('https://i.invalid','officer','active') RETURNING id"
    )
    parcel = (
        "INSERT INTO parcel (jurisdiction_id, code, current_version, created_by, updated_by)"
        " VALUES (:j, :c, 1, :u, :u) RETURNING id"
    )
    yield World(
        conn,
        j1,
        j2,
        user,
        await one(parcel, j=j1, c="P-1", u=user),
        await one(parcel, j=j2, c="P-2", u=user),
    )


def test_every_new_table_is_classified_as_tenant_scoped() -> None:
    expected = {
        "parcel", "parcel_geometry_version", "property", "building_permit", "permit_history",
        "construction_change_candidate", "candidate_review", "candidate_evaluation",
        "inspection_case", "case_state_transition", "case_assignment", "case_finding",
    }  # fmt: skip
    assert expected <= TENANT_TABLES


async def test_forced_rls_and_policies_exist(conn: AsyncConnection) -> None:
    rows = (
        await conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) AS policies "
                "FROM pg_class c WHERE c.relname = ANY(:t) AND c.relkind = 'r'"
            ),
            {"t": sorted(TENANT_TABLES)},
        )
    ).all()
    assert {r.relname for r in rows} == set(TENANT_TABLES)
    assert all(r.relrowsecurity and r.relforcerowsecurity and r.policies >= 1 for r in rows)


async def test_permission_catalogue_is_seeded_without_role_mapping(conn: AsyncConnection) -> None:
    codes = {r[0] for r in await conn.execute(text("SELECT code FROM permission"))}
    assert {"finding:verify", "candidate:create", "case:create", "case:assign"} <= codes
    assert (await conn.execute(text("SELECT count(*) FROM role_permission"))).scalar_one() == 0


async def _seed_history(w: World) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    ids["parcel_geometry_version"] = await w.add(
        "parcel_geometry_version",
        parcel_id=w.parcel1,
        jurisdiction_id=w.j1,
        version=1,
        geometry=Raw(f"ST_Multi({SQUARE})"),
        area_sq_m=100,
        topology_status="clean",
        recorded_by=w.user,
    )
    permit = await w.add(
        "building_permit",
        jurisdiction_id=w.j1,
        permit_number="BP-1",
        status="approved",
        valid_from=DAY,
        sanctioned_floors=2,
        sanctioned_footprint_area_sq_m=100,
        declared_parcel_code="P-1",
        parcel_id=w.parcel1,
        match_status="matched",
        source_system="fixture",
        **w._audit(),
    )
    ids["permit_history"] = await w.add(
        "permit_history",
        permit_id=permit,
        jurisdiction_id=w.j1,
        event="created",
        actor_id=w.user,
    )
    candidate = await w.candidate(w.j1, w.parcel1)
    await w.review(candidate, w.j1, "confirmed")
    ids["candidate_review"] = (
        await w.conn.execute(
            text("SELECT id FROM candidate_review WHERE candidate_id = :c"), {"c": candidate}
        )
    ).scalar_one()
    evaluation = await w.evaluation(candidate, w.j1)
    ids["candidate_evaluation"] = evaluation
    case = await w.add("inspection_case", **w.case_values(candidate, evaluation, w.j1))
    ids["case_state_transition"] = await w.add(
        "case_state_transition",
        case_id=case,
        jurisdiction_id=w.j1,
        to_status="created",
        actor_id=w.user,
    )
    ids["case_assignment"] = await w.add(
        "case_assignment",
        case_id=case,
        jurisdiction_id=w.j1,
        assigned_to=w.user,
        assigned_by=w.user,
    )
    ids["case_finding"] = await w.add(
        "case_finding", case_id=case, jurisdiction_id=w.j1, author_id=w.user, notes="site visit"
    )
    return ids


@pytest.mark.parametrize("table", sorted(APPEND_ONLY))
async def test_history_tables_reject_update_and_delete_for_every_role(w: World, table: str) -> None:
    row = (await _seed_history(w))[table]
    change = f"UPDATE {table} SET jurisdiction_id = jurisdiction_id WHERE id = :i"
    remove = f"DELETE FROM {table} WHERE id = :i"
    # The maintenance role simply holds no UPDATE/DELETE privilege on a history table.
    assert await _state(w.conn, change, i=row) == INSUFFICIENT_PRIVILEGE
    assert await _state(w.conn, remove, i=row) == INSUFFICIENT_PRIVILEGE
    # The table owner holds every privilege (and sees rows through its RLS context) but the
    # trigger still stops the change.
    await w.conn.execute(text("RESET ROLE"))
    try:
        await w.conn.execute(
            text("SELECT set_config('app.jurisdiction_ids', :j, true)"), {"j": str(w.j1)}
        )
        assert await _state(w.conn, change, i=row) == RESTRICT_VIOLATION
        assert await _state(w.conn, remove, i=row) == RESTRICT_VIOLATION
        assert await _state(w.conn, f"TRUNCATE {table} CASCADE") == RESTRICT_VIOLATION
    finally:
        await w.conn.execute(text(f"SET ROLE {ADMIN_ROLE}"))


async def test_a_child_row_must_share_the_jurisdiction_of_its_parent(w: World) -> None:
    permit = {
        "jurisdiction_id": w.j1,
        "permit_number": "BP-X",
        "status": "approved",
        "valid_from": DAY,
        "sanctioned_floors": 2,
        "sanctioned_footprint_area_sq_m": 100,
        "declared_parcel_code": "P-2",
        "match_status": "matched",
        "source_system": "fixture",
        **w._audit(),
    }
    assert await w.try_add("building_permit", parcel_id=w.parcel2, **permit) == CHECK_VIOLATION
    candidate = await w.candidate(w.j1)
    review = w.review_values(candidate, w.j2, "confirmed")
    assert await w.try_add("candidate_review", **review) == CHECK_VIOLATION


async def test_a_candidate_cannot_start_in_any_state_but_unverified(w: World) -> None:
    values = w.candidate_values(w.j1, status="confirmed")
    assert await w.try_add("construction_change_candidate", **values) == RESTRICT_VIOLATION


async def test_candidate_status_changes_only_through_a_matching_recorded_review(w: World) -> None:
    candidate = await w.candidate(w.j1)
    assert await w.set_status(candidate, "confirmed") == RESTRICT_VIOLATION
    await w.review(candidate, w.j1, "rejected", apply=False)
    assert await w.set_status(candidate, "confirmed") == RESTRICT_VIOLATION
    assert await w.set_status(candidate, "rejected") == "ok"


@pytest.mark.parametrize(
    "change",
    [
        "confidence = 0.5",
        "change_type = 'extension'",
        "estimated_floors = 9",
        "provenance_note = 'x'",
        "is_simulated = true",
        "model_name = 'm'",
        f"footprint = {SQUARE}",
    ],
)
async def test_candidate_evidence_is_immutable(w: World, change: str) -> None:
    candidate = await w.candidate(w.j1)
    sql = f"UPDATE construction_change_candidate SET {change} WHERE id = :i"
    assert await _state(w.conn, sql, i=candidate) == RESTRICT_VIOLATION


@pytest.mark.parametrize("status", ["unverified", "needs_evidence", "rejected"])
async def test_release_gate_rejects_a_case_for_a_candidate_not_confirmed(
    w: World, status: str
) -> None:
    candidate = await w.candidate(w.j1)
    if status != "unverified":
        await w.review(candidate, w.j1, status)
    evaluation = await w.evaluation(candidate, w.j1)
    assert await w.try_case(candidate, evaluation, w.j1) == RESTRICT_VIOLATION


async def test_release_gate_accepts_a_confirmed_evaluated_candidate_exactly_once(
    w: World,
) -> None:
    candidate = await w.candidate(w.j1)
    await w.review(candidate, w.j1, "confirmed")
    evaluation = await w.evaluation(candidate, w.j1)
    assert await w.try_case(candidate, evaluation, w.j1) == "ok"
    assert await w.try_case(candidate, evaluation, w.j1) == UNIQUE_VIOLATION


async def test_the_evaluation_must_belong_to_the_candidate(w: World) -> None:
    a = await w.candidate(w.j1)
    b = await w.candidate(w.j1)
    await w.review(a, w.j1, "confirmed")
    assert await w.try_case(a, await w.evaluation(b, w.j1), w.j1) == CHECK_VIOLATION


async def test_a_confirmed_candidate_with_an_open_case_cannot_be_un_confirmed(
    w: World,
) -> None:
    candidate, _case = await w.open_case()
    await w.review(candidate, w.j1, "rejected", apply=False)
    assert await w.set_status(candidate, "rejected") == RESTRICT_VIOLATION


async def test_a_closed_case_is_immutable_and_keeps_its_candidate(w: World) -> None:
    _candidate, case = await w.open_case()
    other = await w.candidate(w.j1)
    update = "UPDATE inspection_case SET {} WHERE id = :i"
    assert await _state(w.conn, update.format("candidate_id = :o"), i=case, o=other) == (
        RESTRICT_VIOLATION
    )
    assert await _state(w.conn, update.format("status = 'dismissed'"), i=case) == "ok"
    assert await _state(w.conn, update.format("priority_score = 1"), i=case) == RESTRICT_VIOLATION


async def test_an_active_case_requires_an_assignee(w: World) -> None:
    _candidate, case = await w.open_case()
    sql = "UPDATE inspection_case SET status = 'assigned' WHERE id = :i"
    assert await _state(w.conn, sql, i=case) == CHECK_VIOLATION


async def test_invalid_geometry_is_rejected_by_the_database(w: World) -> None:
    values = w.candidate_values(w.j1, footprint=Raw(BOWTIE))
    assert await w.try_add("construction_change_candidate", **values) == CHECK_VIOLATION


async def test_an_ai_candidate_requires_model_provenance(w: World) -> None:
    values = w.candidate_values(w.j1, source_type="ai_detection")
    assert await w.try_add("construction_change_candidate", **values) == CHECK_VIOLATION


# --- Row-level security, exercised as the application role ------------------------------------
async def _session_state(session: object, sql: str, **params: object) -> str | None:
    try:
        async with session.begin_nested():  # type: ignore[attr-defined]
            await session.execute(text(sql), params)  # type: ignore[attr-defined]
    except DBAPIError as exc:
        return getattr(exc.orig, "sqlstate", None)
    return None


async def test_application_role_sees_and_writes_only_permitted_jurisdictions(
    migrated_database: str,
) -> None:
    owner = create_async_engine(migrated_database)
    admin = role_engine(migrated_database, ADMIN_ROLE)
    app = role_engine(migrated_database, APP_ROLE)
    parcel = (
        "INSERT INTO parcel (jurisdiction_id, code, current_version, created_by, updated_by)"
        " VALUES (:j, :c, 1, :u, :u)"
    )
    try:
        async with owner.begin() as c:
            await truncate_cascade(c, RESET_TABLES)
        async with admin.begin() as c:
            root = (
                await c.execute(
                    text(
                        "INSERT INTO jurisdiction (code,name,level)"
                        " VALUES ('N','N','national') RETURNING id"
                    )
                )
            ).scalar_one()
            state = (
                "INSERT INTO jurisdiction (code,name,level,parent_id)"
                " VALUES (:c,:c,'state',:p) RETURNING id"
            )
            ja = (await c.execute(text(state), {"c": "ja", "p": root})).scalar_one()
            jb = (await c.execute(text(state), {"c": "jb", "p": root})).scalar_one()
            user = (
                await c.execute(
                    text(
                        "INSERT INTO user_account (issuer,subject,status)"
                        " VALUES ('https://i.invalid','u','active') RETURNING id"
                    )
                )
            ).scalar_one()
            for j, code in ((ja, "A"), (jb, "B")):
                await c.execute(text(parcel), {"j": j, "c": code, "u": user})

        def sessions() -> async_sessionmaker:  # type: ignore[type-arg]
            return async_sessionmaker(app, expire_on_commit=False)

        async with tenant_session(sessions, user_id=user, jurisdiction_ids=[ja]) as s:
            assert {r.code for r in await s.execute(text("SELECT code FROM parcel"))} == {"A"}
            assert await _session_state(s, parcel, j=jb, c="Z", u=user) == "42501"
        async with tenant_session(sessions, user_id=user, jurisdiction_ids=[]) as s:
            assert (await s.execute(text("SELECT count(*) FROM parcel"))).scalar_one() == 0
        async with tenant_session(sessions, user_id=user, jurisdiction_ids=[ja, jb]) as s:
            assert await _session_state(s, "DELETE FROM parcel") == INSUFFICIENT_PRIVILEGE
            assert await _session_state(s, "TRUNCATE parcel") == INSUFFICIENT_PRIVILEGE
            history = "UPDATE candidate_review SET justification = 'x'"
            assert await _session_state(s, history) == INSUFFICIENT_PRIVILEGE
    finally:
        async with owner.begin() as c:
            await truncate_cascade(c, RESET_TABLES)
        await owner.dispose()
        await admin.dispose()
        await app.dispose()


async def test_the_reset_helper_leaves_every_trigger_enabled(migrated_database: str) -> None:
    owner = create_async_engine(migrated_database)
    try:
        async with owner.begin() as c:
            await truncate_cascade(c, "parcel")
        async with owner.connect() as c:
            disabled = (
                await c.execute(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgenabled = 'D' AND NOT tgisinternal"
                    )
                )
            ).scalar_one()
        assert disabled == 0
    finally:
        await owner.dispose()
