"""PostgreSQL implementation of :class:`app.core.authz.AccessStore`."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.authz import AccessUser, FirstSeen, SessionState

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

_INSERT_SESSION = text(
    """
    INSERT INTO auth_session (issuer, session_key, user_id, expires_at)
    VALUES (:issuer, :session_key, :user_id, :expires_at)
    ON CONFLICT (issuer, session_key) DO NOTHING
    RETURNING id
    """
)
_SESSION_STATE = text(
    """
    SELECT user_id, revoked_at IS NOT NULL AS revoked FROM auth_session
    WHERE issuer = :issuer AND session_key = :session_key
    """
)
_REVOKE_SESSION = text(
    """
    INSERT INTO auth_session (issuer, session_key, user_id, expires_at,
                              revoked_at, revoked_by, revoke_reason)
    VALUES (:issuer, :session_key, :user_id, :expires_at, :at, :revoked_by, :reason)
    ON CONFLICT (issuer, session_key) DO UPDATE
        SET revoked_at = COALESCE(auth_session.revoked_at, EXCLUDED.revoked_at),
            revoked_by = COALESCE(auth_session.revoked_by, EXCLUDED.revoked_by),
            revoke_reason = COALESCE(auth_session.revoke_reason, EXCLUDED.revoke_reason)
        WHERE auth_session.user_id = EXCLUDED.user_id
    RETURNING id
    """
)
_REVOKE_USER = text(
    """
    UPDATE user_account
    SET revoked_before = GREATEST(COALESCE(revoked_before, :at), :at), updated_by = :revoked_by
    WHERE id = :user_id AND NOT is_deleted
    """
)
_ASSIGNMENT_JURISDICTIONS = text(
    """
    SELECT DISTINCT jurisdiction_id FROM role_assignment
    WHERE user_id = :user_id AND revoked_at IS NULL
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

    async def register_session(
        self,
        *,
        user_id: uuid.UUID,
        issuer: str,
        session_key: str,
        expires_at: datetime,
        at: datetime,
        on_first_seen: FirstSeen | None = None,
    ) -> SessionState:
        params = {"issuer": issuer, "session_key": session_key}
        async with self._sessionmaker()() as session, session.begin():
            inserted = (
                await session.execute(
                    _INSERT_SESSION, {**params, "user_id": user_id, "expires_at": expires_at}
                )
            ).first()
            if inserted is not None:
                # Still inside the transaction: if auditing fails, the registration rolls back.
                if on_first_seen is not None:
                    await on_first_seen()
                return SessionState(is_new=True, revoked=False)
            row = (await session.execute(_SESSION_STATE, params)).one()
        # A session key belongs to one user; a different user presenting it is rejected.
        return SessionState(is_new=False, revoked=bool(row.revoked) or row.user_id != user_id)

    async def revoke_session(
        self,
        *,
        user_id: uuid.UUID,
        issuer: str,
        session_key: str,
        expires_at: datetime,
        revoked_by: uuid.UUID,
        reason: str,
        at: datetime,
    ) -> None:
        async with self._sessionmaker()() as session, session.begin():
            await session.execute(
                _REVOKE_SESSION,
                {
                    "issuer": issuer,
                    "session_key": session_key,
                    "user_id": user_id,
                    "expires_at": expires_at,
                    "revoked_by": revoked_by,
                    "reason": reason,
                    "at": at,
                },
            )

    async def revoke_user_sessions(
        self, *, user_id: uuid.UUID, at: datetime, revoked_by: uuid.UUID, reason: str
    ) -> None:
        async with self._sessionmaker()() as session, session.begin():
            await session.execute(
                _REVOKE_USER, {"user_id": user_id, "at": at, "revoked_by": revoked_by}
            )

    async def assignment_jurisdictions(self, *, user_id: uuid.UUID) -> frozenset[uuid.UUID]:
        async with self._sessionmaker()() as session:
            rows = await session.execute(_ASSIGNMENT_JURISDICTIONS, {"user_id": user_id})
            return frozenset(row.jurisdiction_id for row in rows)
