"""Audited access through the bypass-capable maintenance role (ADR-0011 decision 6).

The web application never imports this module (enforced by an import-linter contract). A
caller supplies a sessionmaker bound to the ``satrak_admin`` role (BYPASSRLS) and a reason;
the use is written to the security audit log *before* any work happens, and the work is
refused if that record cannot be written.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security_audit import PRIVILEGED_DB_USED, SecurityAuditLog, SecurityEvent

logger = structlog.get_logger("db.privileged")


@asynccontextmanager
async def privileged_session(
    admin_sessions: Callable[[], async_sessionmaker[AsyncSession]],
    *,
    audit: SecurityAuditLog,
    operator: str,
    reason: str,
) -> AsyncIterator[AsyncSession]:
    """A transaction on the bypass-capable role; audited first, fails closed."""
    if not reason.strip() or not operator.strip():
        raise ValueError("operator and reason are required for privileged database access")
    await audit.record(
        SecurityEvent(
            event_type=PRIVILEGED_DB_USED,
            outcome="success",
            details={"operator": operator[:100], "reason": reason[:150]},
        )
    )
    logger.warning("privileged_db_access", operator=operator, reason=reason)
    async with admin_sessions()() as session, session.begin():
        yield session
