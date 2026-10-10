"""Access-control foundation: jurisdictions, organizations, users, roles, assignments.

Creates the identity/organization/jurisdiction tables (ADR-0011, ADR-0012, ADR-0013):

* ``jurisdiction`` — national → state → city → ward hierarchy with an EPSG:4326 boundary.
  A trigger rejects cycles and children that are not strictly deeper than their parent.
* ``organization`` and ``role_assignment`` — tenant-owned, non-null ``jurisdiction_id``.
* ``user_account`` — local identity keyed by (issuer, subject), starts with no permissions.
* ``role``, ``permission``, ``role_permission``.

Downgrade policy: this migration only creates new tables, so ``downgrade()`` drops exactly
what ``upgrade()`` created (and nothing pre-existing). It is destructive to identity and
assignment data created after the upgrade, which is acceptable only before production
use; once real data exists, rollback must be a restore, not a downgrade.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEVELS = "('national', 'state', 'city', 'ward')"
_STATUSES = "('pending_role_assignment', 'active', 'disabled')"
_KINDS = "('assignment', 'cross_jurisdiction_grant')"


def _uuid_pk() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _actors() -> list[sa.Column[object]]:
    return [
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    ]


def _versioned_tail() -> list[sa.Column[object]]:
    return [
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "jurisdiction",
        _uuid_pk(),
        *_timestamps(),
        *_actors(),
        *_versioned_tail(),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column(
            "boundary",
            geoalchemy2.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["jurisdiction.id"],
            name="fk_jurisdiction_parent_id_jurisdiction",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jurisdiction"),
        sa.UniqueConstraint("code", name="uq_jurisdiction_code"),
        sa.CheckConstraint(f"level IN {_LEVELS}", name="ck_jurisdiction_level_valid"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_jurisdiction_not_own_parent"
        ),
        sa.CheckConstraint(
            "(level = 'national') = (parent_id IS NULL)", name="ck_jurisdiction_root_is_national"
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0 AND length(btrim(name)) > 0", name="ck_jurisdiction_named"
        ),
    )
    op.create_index("ix_jurisdiction_parent_id", "jurisdiction", ["parent_id"])
    op.create_index(
        "idx_jurisdiction_boundary", "jurisdiction", ["boundary"], postgresql_using="gist"
    )

    # Hierarchy integrity: no cycles, and a child is strictly deeper than its parent.
    op.execute(
        """
        CREATE FUNCTION jurisdiction_check_hierarchy() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            parent_level text;
            depth_of CONSTANT text[] := ARRAY['national', 'state', 'city', 'ward'];
        BEGIN
            IF NEW.parent_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT level INTO parent_level FROM jurisdiction WHERE id = NEW.parent_id;
            IF parent_level IS NULL THEN
                RAISE EXCEPTION 'parent jurisdiction does not exist' USING ERRCODE = '23503';
            END IF;
            IF array_position(depth_of, NEW.level) <= array_position(depth_of, parent_level) THEN
                RAISE EXCEPTION 'jurisdiction level % must be deeper than parent level %',
                    NEW.level, parent_level USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                WITH RECURSIVE ancestors(id, parent_id) AS (
                    SELECT j.id, j.parent_id FROM jurisdiction j WHERE j.id = NEW.parent_id
                    UNION ALL
                    SELECT j.id, j.parent_id FROM jurisdiction j
                    JOIN ancestors a ON j.id = a.parent_id
                )
                SELECT 1 FROM ancestors WHERE id = NEW.id
            ) THEN
                RAISE EXCEPTION 'jurisdiction hierarchy cycle' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER jurisdiction_hierarchy
        BEFORE INSERT OR UPDATE OF parent_id, level ON jurisdiction
        FOR EACH ROW EXECUTE FUNCTION jurisdiction_check_hierarchy();
        """
    )

    op.create_table(
        "organization",
        _uuid_pk(),
        *_timestamps(),
        *_actors(),
        *_versioned_tail(),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name="fk_organization_jurisdiction_id_jurisdiction",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organization"),
        sa.UniqueConstraint("jurisdiction_id", "name", name="uq_organization_jurisdiction_name"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_organization_named"),
    )
    op.create_index("ix_organization_jurisdiction_id", "organization", ["jurisdiction_id"])

    op.create_table(
        "user_account",
        _uuid_pk(),
        *_timestamps(),
        *_actors(),
        *_versioned_tail(),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column(
            "status", sa.String(32), server_default="pending_role_assignment", nullable=False
        ),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name="fk_user_account_organization_id_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_account"),
        sa.UniqueConstraint("issuer", "subject", name="uq_user_account_issuer_subject"),
        sa.CheckConstraint(f"status IN {_STATUSES}", name="ck_user_account_status_valid"),
    )

    op.create_table(
        "permission",
        _uuid_pk(),
        *_timestamps(),
        *_actors(),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_permission"),
        sa.UniqueConstraint("code", name="uq_permission_code"),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$'", name="ck_permission_code_format"
        ),
    )

    op.create_table(
        "role",
        _uuid_pk(),
        *_timestamps(),
        *_actors(),
        *_versioned_tail(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_role"),
        sa.UniqueConstraint("code", name="uq_role_code"),
        sa.CheckConstraint("length(btrim(code)) > 0", name="ck_role_coded"),
    )

    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="fk_role_permission_role_id_role", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permission.id"],
            name="fk_role_permission_permission_id_permission",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permission"),
    )

    op.create_table(
        "role_assignment",
        _uuid_pk(),
        *_timestamps(),
        *_actors(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), server_default="assignment", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_role_assignment_user_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="fk_role_assignment_role_id_role", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name="fk_role_assignment_jurisdiction_id_jurisdiction",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["user_account.id"],
            name="fk_role_assignment_revoked_by_user_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_role_assignment"),
        sa.CheckConstraint(f"kind IN {_KINDS}", name="ck_role_assignment_kind_valid"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="ck_role_assignment_window_ordered"
        ),
        sa.CheckConstraint(
            "kind <> 'cross_jurisdiction_grant' OR "
            "(valid_to IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_role_assignment_grant_expires_with_reason",
        ),
    )
    op.create_index(
        "ix_role_assignment_user_jurisdiction", "role_assignment", ["user_id", "jurisdiction_id"]
    )
    op.create_index("ix_role_assignment_jurisdiction_id", "role_assignment", ["jurisdiction_id"])


def downgrade() -> None:
    op.drop_table("role_assignment")
    op.drop_table("role_permission")
    op.drop_table("role")
    op.drop_table("permission")
    op.drop_table("user_account")
    op.drop_table("organization")
    op.execute("DROP TRIGGER IF EXISTS jurisdiction_hierarchy ON jurisdiction")
    op.drop_table("jurisdiction")
    op.execute("DROP FUNCTION IF EXISTS jurisdiction_check_hierarchy()")
