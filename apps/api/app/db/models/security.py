"""Session registry (revocation) and the append-only security audit log (Story 5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security_audit import EVENT_TYPES, OUTCOMES
from app.db.base import Base
from app.db.models.access import _in


class AuthSession(Base):
    """A session (IdP ``sid``, else token ``jti``) the API has seen; the revocation target."""

    __tablename__ = "auth_session"
    __table_args__ = (
        UniqueConstraint("issuer", "session_key", name="uq_auth_session_issuer_session_key"),
        Index("ix_auth_session_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    session_key: Mapped[str] = mapped_column(String(512), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Rows past this instant can be pruned: the token itself has expired by then.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    """Append-only, hash-chained security events. UPDATE/DELETE/TRUNCATE are rejected."""

    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(_in("event_type", tuple(sorted(EVENT_TYPES))), name="event_type_valid"),
        CheckConstraint(_in("outcome", tuple(sorted(OUTCOMES))), name="outcome_valid"),
        UniqueConstraint("id", name="uq_audit_event_id"),
        UniqueConstraint("hash", name="uq_audit_event_hash"),
        Index("ix_audit_event_occurred_at", "occurred_at"),
        Index("ix_audit_event_actor_user_id", "actor_user_id"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # No foreign keys: audit rows must outlive (and never block) changes to what they describe.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    permission: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
