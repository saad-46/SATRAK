"""SQLAlchemy declarative base and reusable ORM mixins.

These are the *persistence* counterparts to the pure-domain entities in
:mod:`app.shared.domain`. They provide the audit envelope every table carries —
UUID primary key, timestamps, created/updated actors, an optimistic-concurrency
version, and soft-delete columns — composed via mixins so a concrete table opts
into exactly the columns it needs.

A deterministic constraint-naming convention makes ``alembic --autogenerate``
produce stable, reviewable migration names. No feature tables are declared here
(Epic 2 scope) — only the abstract bases future contexts map their aggregates to.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable names for indexes/constraints -> clean, reviewable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --- Composable mixins -------------------------------------------------------
class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key (preferred over serial ints for distributed data)."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Adds server-managed created/updated timestamps (UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActorMixin:
    """Adds created_by / updated_by actor references (user ids)."""

    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class VersionMixin:
    """Adds an integer version column for optimistic concurrency control.

    A concrete aggregate table can enable SQLAlchemy's optimistic locking by
    setting ``__mapper_args__ = {"version_id_col": <table>.version}``.
    """

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class SoftDeleteMixin:
    """Adds soft-delete columns so rows are hidden, not physically removed.

    Legal defensibility requires retaining history; deletes are logical.
    """

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Ready-made abstract bases -----------------------------------------------
class BaseEntity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """UUID id + timestamps. The minimal persistent entity."""

    __abstract__ = True


class AuditEntity(BaseEntity, ActorMixin):
    """BaseEntity + created/updated actors."""

    __abstract__ = True


class VersionedEntity(AuditEntity, VersionMixin, SoftDeleteMixin):
    """The full audit envelope: id, timestamps, actors, version, soft-delete.

    This is the default base for aggregate-root tables and mirrors the fields on
    the domain :class:`app.shared.domain.entity.Entity`.
    """

    __abstract__ = True
