"""Transaction-scoped jurisdiction context for row-level security (ADR-0011).

The context is written with ``set_config(name, value, true)`` -- the parameterizable form of
``SET LOCAL`` -- so PostgreSQL discards it at COMMIT or ROLLBACK. A pooled connection can
therefore never carry one request's jurisdictions into the next, whatever happens in between
(exceptions, cancellation, rollback). Sessions here are always transactional: the context is
applied as the first statement of the transaction.

Callers must derive ``jurisdiction_ids`` server-side (``AccessContext.jurisdictions``), never
from client input.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger("db.rls")

_SET_CONTEXT = text(
    "SELECT set_config('app.user_id', :user_id, true), "
    "set_config('app.jurisdiction_ids', :jurisdictions, true)"
)

Sessions = Callable[[], async_sessionmaker[AsyncSession]]


async def apply_context(
    session: AsyncSession, *, user_id: uuid.UUID | None, jurisdiction_ids: Iterable[uuid.UUID]
) -> None:
    """Set the RLS context for the current transaction (must be called inside one)."""
    if not session.in_transaction():
        raise RuntimeError("the RLS context can only be set inside a transaction")
    await session.execute(
        _SET_CONTEXT,
        {
            "user_id": str(user_id) if user_id is not None else "",
            "jurisdictions": ",".join(sorted(str(j) for j in set(jurisdiction_ids))),
        },
    )


@asynccontextmanager
async def tenant_session(
    sessions: Sessions, *, user_id: uuid.UUID | None, jurisdiction_ids: Iterable[uuid.UUID]
) -> AsyncIterator[AsyncSession]:
    """A transaction whose rows are limited to ``jurisdiction_ids``; commits on success."""
    async with sessions()() as session, session.begin():
        await apply_context(session, user_id=user_id, jurisdiction_ids=jurisdiction_ids)
        yield session


@asynccontextmanager
async def worker_session(
    sessions: Sessions, *, job: str, jurisdiction_ids: Iterable[uuid.UUID]
) -> AsyncIterator[AsyncSession]:
    """Background jobs get an explicit, non-empty jurisdiction scope: there is no ambient bypass.

    A job that genuinely needs every jurisdiction must enumerate them (or run through
    :func:`app.db.privileged.privileged_session`, which is audited).
    """
    scope = frozenset(jurisdiction_ids)
    if not scope:
        raise ValueError(f"worker job {job!r} must declare at least one jurisdiction")
    logger.info("worker_scope", job=job, jurisdictions=len(scope))
    async with tenant_session(sessions, user_id=None, jurisdiction_ids=scope) as session:
        yield session
