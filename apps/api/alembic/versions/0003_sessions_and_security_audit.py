"""Session registry for revocation, and the append-only security audit log.

* ``auth_session`` — one row per IdP session (``sid``, else token ``jti``) the API has seen;
  setting ``revoked_at`` rejects that session on its very next request (ADR-0013 E).
* ``audit_event`` — hash-chained security events. Triggers reject UPDATE, DELETE and TRUNCATE
  for every role including the table owner; only DROP TABLE (this migration's downgrade) or a
  superuser disabling the triggers can remove rows, and either breaks/ends the hash chain.

Downgrade drops exactly what ``upgrade()`` created. It destroys the audit trail, so like 0002
it is acceptable only before production use; afterwards rollback must be a restore.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = "('access.denied', 'session.revoked', 'user.login_failed', 'user.logged_in')"
_OUTCOMES = "('denied', 'failure', 'success')"


def upgrade() -> None:
    op.create_table(
        "auth_session",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("session_key", sa.String(512), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
            name="fk_auth_session_user_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("issuer", "session_key", name="uq_auth_session_issuer_session_key"),
    )
    op.create_index("ix_auth_session_user_id", "auth_session", ["user_id"])
    op.create_index("ix_auth_session_expires_at", "auth_session", ["expires_at"])

    op.create_table(
        "audit_event",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("jurisdiction_id", sa.Uuid(), nullable=True),
        sa.Column("permission", sa.String(128), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.CheckConstraint(f"event_type IN {_EVENT_TYPES}", name="ck_audit_event_event_type_valid"),
        sa.CheckConstraint(f"outcome IN {_OUTCOMES}", name="ck_audit_event_outcome_valid"),
        sa.UniqueConstraint("id", name="uq_audit_event_id"),
        sa.UniqueConstraint("hash", name="uq_audit_event_hash"),
    )
    op.create_index("ix_audit_event_occurred_at", "audit_event", ["occurred_at"])
    op.create_index("ix_audit_event_actor_user_id", "audit_event", ["actor_user_id"])

    op.execute(
        """
        CREATE FUNCTION audit_event_reject_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_event is append-only (% rejected)', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_event_append_only_rows BEFORE UPDATE OR DELETE ON audit_event "
        "FOR EACH ROW EXECUTE FUNCTION audit_event_reject_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_event_append_only_truncate BEFORE TRUNCATE ON audit_event "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_event_reject_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_event_append_only_truncate ON audit_event")
    op.execute("DROP TRIGGER IF EXISTS audit_event_append_only_rows ON audit_event")
    op.drop_table("audit_event")
    op.execute("DROP FUNCTION IF EXISTS audit_event_reject_change()")
    op.drop_table("auth_session")
