"""Scheduled database maintenance that needs the bypass-capable role (ADR-0011 decision 6).

Run from an operator job, never from the web layer. Each run is audited first through
:func:`app.db.privileged.privileged_session`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security_audit import SecurityAuditLog
from app.db.privileged import privileged_session

_PRUNE = text("DELETE FROM auth_session WHERE expires_at < :cutoff")


async def prune_auth_sessions(
    admin_sessions: Callable[[], async_sessionmaker[AsyncSession]],
    *,
    audit: SecurityAuditLog,
    operator: str,
    now: datetime,
    retention_days: int,
) -> int:
    """Delete session registry rows whose token expired more than ``retention_days`` ago.

    A row is only needed until its token expires (a revoked token must stay refused), so any
    positive retention is safe for revocation; the audit log is append-only and never pruned.
    Returns the number of rows removed.
    """
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    cutoff = now - timedelta(days=retention_days)
    async with privileged_session(
        admin_sessions,
        audit=audit,
        operator=operator,
        reason=f"prune auth_session rows expired before {cutoff.date().isoformat()}",
    ) as session:
        result = await session.execute(_PRUNE, {"cutoff": cutoff})
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
