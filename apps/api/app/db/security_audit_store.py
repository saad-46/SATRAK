"""PostgreSQL implementation of :class:`app.core.security_audit.SecurityAuditLog`."""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security_audit import (
    GENESIS_HASH,
    ChainReport,
    SecurityEvent,
    chain_hash,
)

# Appends are serialized by a transaction-scoped advisory lock so ``prev_hash`` is always the
# hash of the row with the highest ``seq`` and no two events can claim the same predecessor.
_LOCK_KEY = 7_410_001
_BATCH = 1000

_INSERT = text(
    """
    INSERT INTO audit_event (id, occurred_at, event_type, outcome, actor_user_id, jurisdiction_id,
                             permission, ip, request_id, details, prev_hash, hash)
    VALUES (:id, :occurred_at, :event_type, :outcome, :actor_user_id, :jurisdiction_id,
            :permission, :ip, :request_id, CAST(:details AS jsonb), :prev_hash, :hash)
    """
)
_LAST_HASH = text("SELECT hash FROM audit_event ORDER BY seq DESC LIMIT 1")
_PAGE = text(
    """
    SELECT seq, id, occurred_at, event_type, outcome, actor_user_id, jurisdiction_id,
           permission, ip, request_id, details, prev_hash, hash
    FROM audit_event WHERE seq > :after ORDER BY seq LIMIT :limit
    """
)


class SqlSecurityAuditLog:
    def __init__(self, sessionmaker: Callable[[], async_sessionmaker[AsyncSession]]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, event: SecurityEvent) -> None:
        async with self._sessionmaker()() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
            previous = (await session.execute(_LAST_HASH)).scalar() or GENESIS_HASH
            await session.execute(
                _INSERT,
                {
                    "id": event.id,
                    "occurred_at": event.occurred_at,
                    "event_type": event.event_type,
                    "outcome": event.outcome,
                    "actor_user_id": event.actor_user_id,
                    "jurisdiction_id": event.jurisdiction_id,
                    "permission": event.permission,
                    "ip": event.ip,
                    "request_id": event.request_id,
                    "details": json.dumps(dict(event.details)),
                    "prev_hash": previous,
                    "hash": chain_hash(previous, event),
                },
            )

    async def verify_chain(self) -> ChainReport:
        previous = GENESIS_HASH
        checked = 0
        after = 0
        async with self._sessionmaker()() as session:
            while True:
                rows = (await session.execute(_PAGE, {"after": after, "limit": _BATCH})).all()
                if not rows:
                    return ChainReport(True, checked)
                for row in rows:
                    event = SecurityEvent(
                        id=row.id,
                        occurred_at=row.occurred_at,
                        event_type=row.event_type,
                        outcome=row.outcome,
                        actor_user_id=row.actor_user_id,
                        jurisdiction_id=row.jurisdiction_id,
                        permission=row.permission,
                        ip=row.ip,
                        request_id=row.request_id,
                        details=row.details,
                    )
                    if row.prev_hash != previous:
                        return ChainReport(False, checked, row.seq, "broken link")
                    if chain_hash(previous, event) != row.hash:
                        return ChainReport(False, checked, row.seq, "hash mismatch")
                    previous = row.hash
                    checked += 1
                    after = row.seq
