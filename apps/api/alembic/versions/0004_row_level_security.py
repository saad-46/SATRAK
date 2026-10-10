"""Row-level security for tenant-owned tables, least-privilege grants, privileged-use audit type.

ADR-0011: every table with a non-null ``jurisdiction_id`` has RLS enabled **and forced**; the
policies compare the row's jurisdiction with the transaction-local setting
``app.jurisdiction_ids`` (set with ``set_config(..., true)``, i.e. ``SET LOCAL``). With no
setting the visible set is empty (default deny). ``role_assignment`` additionally lets a user
read their *own* assignments (``app.user_id``), which is how permissions are bootstrapped
before any jurisdiction context exists.

Grants go to the ``satrak_app`` role (see ``infra/db/roles.sql``) when it exists; the role is
a cluster-level object that this migration neither creates nor gives a password. The role is
not the table owner, is not a superuser and does not have BYPASSRLS.

Downgrade removes the policies, grants and functions created here (and nothing else); it
restores the previous audit event-type constraint. Existing data is untouched.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("organization", "role_assignment")
_OLD_EVENT_TYPES = "('access.denied', 'session.revoked', 'user.login_failed', 'user.logged_in')"
_NEW_EVENT_TYPES = _OLD_EVENT_TYPES.replace("(", "('privileged_db.used', ", 1)

_GRANTS = {
    "jurisdiction": "SELECT",
    "organization": "SELECT, INSERT, UPDATE",
    "role_assignment": "SELECT, INSERT, UPDATE",
    "user_account": "SELECT, INSERT, UPDATE",
    "role": "SELECT",
    "permission": "SELECT",
    "role_permission": "SELECT",
    "auth_session": "SELECT, INSERT, UPDATE",
    "audit_event": "SELECT, INSERT",  # no UPDATE/DELETE: append-only (also enforced by trigger)
}

_PERMITTED = "jurisdiction_id = ANY (app_permitted_jurisdictions())"


# Break-glass maintenance role (BYPASSRLS). Used only via app.db.privileged; never by the API.
_ADMIN_GRANTS = {
    table: "SELECT, INSERT, UPDATE, DELETE" for table in _GRANTS if table != "audit_event"
} | {"audit_event": "SELECT, INSERT"}


def _if_role(role: str, statement: str) -> str:
    return (
        f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
        f"{statement}; END IF; END $$"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app_permitted_jurisdictions() RETURNS uuid[]
        LANGUAGE sql STABLE AS $$
            SELECT COALESCE(
                string_to_array(
                    NULLIF(current_setting('app.jurisdiction_ids', true), ''), ','
                )::uuid[],
                ARRAY[]::uuid[]
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_current_user_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
        $$
        """
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            f"USING ({_PERMITTED}) WITH CHECK ({_PERMITTED})"
        )
    op.execute(
        "CREATE POLICY own_assignments_read ON role_assignment FOR SELECT "
        "USING (user_id = app_current_user_id())"
    )

    op.execute("ALTER TABLE audit_event DROP CONSTRAINT ck_audit_event_event_type_valid")
    op.execute(
        "ALTER TABLE audit_event ADD CONSTRAINT ck_audit_event_event_type_valid "
        f"CHECK (event_type IN {_NEW_EVENT_TYPES})"
    )

    for table, privileges in _GRANTS.items():
        op.execute(_if_role("satrak_app", f"GRANT {privileges} ON {table} TO satrak_app"))
    for table, privileges in _ADMIN_GRANTS.items():
        op.execute(_if_role("satrak_admin", f"GRANT {privileges} ON {table} TO satrak_admin"))
    for role in ("satrak_app", "satrak_admin"):
        for function in ("app_permitted_jurisdictions()", "app_current_user_id()"):
            op.execute(_if_role(role, f"GRANT EXECUTE ON FUNCTION {function} TO {role}"))


def downgrade() -> None:
    for table in _GRANTS:
        for role in ("satrak_app", "satrak_admin"):
            op.execute(_if_role(role, f"REVOKE ALL ON {table} FROM {role}"))
    op.execute("ALTER TABLE audit_event DROP CONSTRAINT ck_audit_event_event_type_valid")
    op.execute(
        "ALTER TABLE audit_event ADD CONSTRAINT ck_audit_event_event_type_valid "
        f"CHECK (event_type IN {_OLD_EVENT_TYPES})"
    )
    op.execute("DROP POLICY IF EXISTS own_assignments_read ON role_assignment")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app_current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS app_permitted_jurisdictions()")
