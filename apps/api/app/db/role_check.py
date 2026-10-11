"""Startup validation of the application's database role (ADR-0011).

Row-level security protects tenants only if the API connects as an unprivileged role. This
check refuses roles that would silently bypass it: superusers, ``BYPASSRLS``, roles that
inherit from such a role, table owners (an owner can disable RLS), and roles that can create
roles or databases. It also verifies that every jurisdiction-owned table has row-level security
enabled **and** forced. It inspects ``current_user``; a pooler or ``SET ROLE`` setup is judged
by the role actually in effect.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.tenancy import GLOBAL_TABLES, TENANT_TABLES


class UnsafeDatabaseRoleError(RuntimeError):
    """The configured database role or schema would bypass tenant isolation."""


@dataclass(frozen=True, slots=True)
class RoleReport:
    role: str
    problems: tuple[str, ...]

    @property
    def safe(self) -> bool:
        return not self.problems


_INSPECT = text(
    """
    WITH app AS (
        -- Every ordinary/partitioned table outside the system schemas; partition children and
        -- extension-owned tables (PostGIS topology, spatial_ref_sys, ...) are excluded.
        SELECT c.oid, n.nspname, c.relname::text AS relname, c.relowner,
               c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%'
    )
    SELECT
        r.rolname AS role,
        r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
        EXISTS (
            SELECT 1 FROM pg_roles x
            WHERE x.oid <> r.oid AND (x.rolsuper OR x.rolbypassrls)
              AND pg_has_role(r.oid, x.oid, 'MEMBER')
        ) AS inherits_privileged,
        COALESCE((
            SELECT array_agg(a.nspname || '.' || a.relname ORDER BY a.nspname, a.relname)
            FROM app a WHERE pg_has_role(r.oid, a.relowner, 'MEMBER')
        ), ARRAY[]::text[]) AS owned_tables,
        -- in neither reviewed list (tenant / global), or outside the public schema
        COALESCE((
            SELECT array_agg(a.nspname || '.' || a.relname ORDER BY a.nspname, a.relname)
            FROM app a
            WHERE NOT (a.nspname = 'public'
                       AND (a.relname = ANY (CAST(:tenant_tables AS text[]))
                            OR a.relname = ANY (CAST(:global_tables AS text[]))))
        ), ARRAY[]::text[]) AS unclassified_tables,
        -- tenant-owned (declared, or carrying jurisdiction_id) without enabled + forced RLS
        COALESCE((
            SELECT array_agg(a.relname ORDER BY a.relname)
            FROM app a
            WHERE a.nspname = 'public'
              AND a.relname <> ALL (CAST(:global_tables AS text[]))
              AND (a.relname = ANY (CAST(:tenant_tables AS text[]))
                   OR EXISTS (
                       SELECT 1 FROM pg_attribute t
                       WHERE t.attrelid = a.oid AND t.attname = 'jurisdiction_id'
                         AND NOT t.attisdropped))
              AND NOT (a.relrowsecurity AND a.relforcerowsecurity)
        ), ARRAY[]::text[]) AS unprotected_tables,
        COALESCE((
            SELECT array_agg(t ORDER BY t)
            FROM unnest(CAST(:tenant_tables AS text[])) AS t
            WHERE NOT EXISTS (
                SELECT 1 FROM pg_policies pol
                WHERE pol.schemaname = 'public' AND pol.tablename = t
            )
        ), ARRAY[]::text[]) AS tenant_tables_without_policy,
        -- declared tenant tables that are absent, or lack a non-null jurisdiction_id
        COALESCE((
            SELECT array_agg(t ORDER BY t)
            FROM unnest(CAST(:tenant_tables AS text[])) AS t
            WHERE NOT EXISTS (
                SELECT 1 FROM app a JOIN pg_attribute k ON k.attrelid = a.oid
                WHERE a.nspname = 'public' AND a.relname = t
                  AND k.attname = 'jurisdiction_id' AND k.attnotnull AND NOT k.attisdropped
            )
        ), ARRAY[]::text[]) AS tenant_tables_malformed
    FROM pg_roles r WHERE r.rolname = current_user
    """
)


async def inspect_application_role(engine: AsyncEngine) -> RoleReport:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                _INSPECT,
                {"global_tables": sorted(GLOBAL_TABLES), "tenant_tables": sorted(TENANT_TABLES)},
            )
        ).one()
    problems: list[str] = []
    if row.rolsuper:
        problems.append("role is a superuser")
    if row.rolbypassrls:
        problems.append("role has BYPASSRLS")
    if row.inherits_privileged:
        problems.append("role inherits from a superuser or BYPASSRLS role")
    if row.rolcreaterole or row.rolcreatedb:
        problems.append("role can create roles or databases")
    if row.owned_tables:
        problems.append(f"role owns tables (an owner can disable RLS): {list(row.owned_tables)}")
    if row.unclassified_tables:
        problems.append(
            f"tables classified neither as tenant nor as global (app/db/tenancy.py): "
            f"{list(row.unclassified_tables)}"
        )
    if row.unprotected_tables:
        problems.append(
            f"jurisdiction tables without enabled and forced RLS: {list(row.unprotected_tables)}"
        )
    if row.tenant_tables_malformed:
        problems.append(
            f"tenant tables missing or without a NOT NULL jurisdiction_id: "
            f"{list(row.tenant_tables_malformed)}"
        )
    if row.tenant_tables_without_policy:
        problems.append(f"tenant tables without a policy: {list(row.tenant_tables_without_policy)}")
    return RoleReport(role=row.role, problems=tuple(problems))


async def assert_safe_application_role(engine: AsyncEngine) -> RoleReport:
    """Raise :class:`UnsafeDatabaseRoleError` unless the role and schema are safe."""
    report = await inspect_application_role(engine)
    if not report.safe:
        raise UnsafeDatabaseRoleError(
            f"unsafe database role {report.role!r}: " + "; ".join(report.problems)
        )
    return report
