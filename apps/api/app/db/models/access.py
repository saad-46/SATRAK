"""Identity, organization and jurisdiction tables (access-control foundation).

Tenancy follows ADR-0011: every tenant-owned row carries a non-null ``jurisdiction_id``
(``organization``, ``role_assignment``); row-level security is added in a later story.
``jurisdiction``, ``user_account``, ``role`` and ``permission`` are global tables: a caller
must be resolved before any jurisdiction context exists.

Vector geometry is EPSG:4326 (ADR-0012).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditEntity, Base, VersionedEntity

JURISDICTION_LEVELS = ("national", "state", "city", "ward")
USER_STATUSES = ("pending_role_assignment", "active", "disabled")
ASSIGNMENT_KINDS = ("assignment", "cross_jurisdiction_grant")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Jurisdiction(VersionedEntity):
    """A node in the national → state → city → ward hierarchy (PRD §3.3.1)."""

    __tablename__ = "jurisdiction"
    __table_args__ = (
        CheckConstraint(_in("level", JURISDICTION_LEVELS), name="level_valid"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        CheckConstraint("(level = 'national') = (parent_id IS NULL)", name="root_is_national"),
        CheckConstraint("length(btrim(code)) > 0 AND length(btrim(name)) > 0", name="named"),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jurisdiction.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    boundary: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=True
    )


class Organization(VersionedEntity):
    """An agency/department operating inside exactly one jurisdiction (tenant-owned)."""

    __tablename__ = "organization"
    __table_args__ = (
        UniqueConstraint("jurisdiction_id", "name", name="uq_organization_jurisdiction_name"),
        CheckConstraint("length(btrim(name)) > 0", name="named"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jurisdiction.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class UserAccount(VersionedEntity):
    """A local identity keyed by (issuer, subject). Holds no permissions itself."""

    __tablename__ = "user_account"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_user_account_issuer_subject"),
        CheckConstraint(_in("status", USER_STATUSES), name="status_valid"),
    )

    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_role_assignment",
        server_default="pending_role_assignment",
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="RESTRICT"), nullable=True
    )
    # Tokens issued before this instant are rejected (revocation; ADR-0013 E).
    revoked_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Permission(AuditEntity):
    __tablename__ = "permission"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$'", name="code_format"),
    )

    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Role(VersionedEntity):
    __tablename__ = "role"
    __table_args__ = (CheckConstraint("length(btrim(code)) > 0", name="coded"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permission.id", ondelete="RESTRICT"), primary_key=True
    )


class RoleAssignment(AuditEntity):
    """A role held by a user within a jurisdiction (and, by hierarchy, its descendants).

    ``cross_jurisdiction_grant`` rows are the time-bound, reasoned, auditable exceptions
    allowed by PRD FR-18.5; they must expire and must say why.
    """

    __tablename__ = "role_assignment"
    __table_args__ = (
        CheckConstraint(_in("kind", ASSIGNMENT_KINDS), name="kind_valid"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="window_ordered"),
        CheckConstraint(
            "kind <> 'cross_jurisdiction_grant' OR "
            "(valid_to IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="grant_expires_with_reason",
        ),
        Index("ix_role_assignment_user_jurisdiction", "user_id", "jurisdiction_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("role.id", ondelete="RESTRICT"), nullable=False
    )
    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jurisdiction.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="assignment", server_default="assignment"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=True
    )
