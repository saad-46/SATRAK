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
    SELECT
        r.rolname AS role,
        r.rolsuper, r.rolbypassrls, r.rolcreaterole, r.rolcreatedb,
        EXISTS (
            SELECT 1 FROM pg_roles x
            WHERE x.oid <> r.oid AND (x.rolsuper OR x.rolbypassrls)
              AND pg_has_role(r.oid, x.oid, 'MEMBER')
        ) AS inherits_privileged,
        COALESCE((
            SELECT array_agg(c.relname::text ORDER BY c.relname)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
              AND pg_has_role(r.oid, c.relowner, 'MEMBER')
        ), ARRAY[]::text[]) AS owned_tables,
        COALESCE((
            SELECT array_agg(c.relname::text ORDER BY c.relname)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
              AND c.relname::text <> ALL (CAST(:global_tables AS text[]))
              AND EXISTS (
                  SELECT 1 FROM pg_attribute a
                  WHERE a.attrelid = c.oid AND a.attname = 'jurisdiction_id'
                    AND NOT a.attisdropped
              )
              AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
        ), ARRAY[]::text[]) AS unprotected_tables,
        COALESCE((
            SELECT array_agg(t ORDER BY t)
            FROM unnest(CAST(:tenant_tables AS text[])) AS t
            WHERE NOT EXISTS (
                SELECT 1 FROM pg_policies pol
                WHERE pol.schemaname = 'public' AND pol.tablename = t
            )
        ), ARRAY[]::text[]) AS tenant_tables_without_policy
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
    if row.unprotected_tables:
        problems.append(
            f"jurisdiction tables without enabled and forced RLS: {list(row.unprotected_tables)}"
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
