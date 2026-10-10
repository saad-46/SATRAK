"""PostgreSQL implementation of :class:`app.core.authz.AccessStore`."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.authz import AccessUser

# Descendants-or-self of every jurisdiction where the user holds a currently valid assignment
# whose role carries the permission. Disabled users, revoked/expired/not-yet-valid assignments,
# soft-deleted roles and jurisdictions yield nothing (default deny).
_PERMITTED = text(
    """
    WITH RECURSIVE granted(id) AS (
        SELECT ra.jurisdiction_id
        FROM role_assignment ra
        JOIN user_account u ON u.id = ra.user_id
        JOIN role r ON r.id = ra.role_id
        JOIN role_permission rp ON rp.role_id = r.id
        JOIN permission p ON p.id = rp.permission_id
        JOIN jurisdiction j ON j.id = ra.jurisdiction_id
        WHERE ra.user_id = :user_id
          AND p.code = :permission
          AND u.status <> 'disabled' AND NOT u.is_deleted
          AND NOT r.is_deleted AND NOT j.is_deleted
          AND ra.revoked_at IS NULL
          AND ra.valid_from <= :at
          AND (ra.valid_to IS NULL OR ra.valid_to > :at)
    ),
    tree(id) AS (
        SELECT id FROM granted
        UNION
        SELECT c.id FROM jurisdiction c JOIN tree t ON c.parent_id = t.id WHERE NOT c.is_deleted
    )
    SELECT id FROM tree
    """
)

_UPSERT = text(
    """
    INSERT INTO user_account (issuer, subject) VALUES (:issuer, :subject)
    ON CONFLICT (issuer, subject) DO NOTHING
    """
)
_SELECT = text(
    """
    SELECT id, status, revoked_before FROM user_account
    WHERE issuer = :issuer AND subject = :subject AND NOT is_deleted
    """
)


class SqlAccessStore:
    def __init__(self, sessionmaker: Callable[[], async_sessionmaker[AsyncSession]]) -> None:
        # A factory, not a sessionmaker: the engine is created lazily on first use.
        self._sessionmaker = sessionmaker

    async def get_or_create_user(self, *, issuer: str, subject: str) -> AccessUser:
        params = {"issuer": issuer, "subject": subject}
        async with self._sessionmaker()() as session, session.begin():
            await session.execute(_UPSERT, params)
            row = (await session.execute(_SELECT, params)).one()
        return AccessUser(id=row.id, status=row.status, revoked_before=row.revoked_before)

    async def permitted_jurisdictions(
        self, *, user_id: uuid.UUID, permission: str, at: datetime
    ) -> frozenset[uuid.UUID]:
        async with self._sessionmaker()() as session:
            rows = await session.execute(
                _PERMITTED, {"user_id": user_id, "permission": permission, "at": at}
            )
            return frozenset(row.id for row in rows)
