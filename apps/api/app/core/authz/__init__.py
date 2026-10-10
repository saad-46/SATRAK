"""Authorization primitives: default-deny, jurisdiction-scoped permission checks (ADR-0011/0013).

An :class:`AccessContext` is the single answer to "which jurisdictions may this caller act in
for this permission?". Endpoints filter list results by it and check object access with
:meth:`AccessContext.require`; the same set later feeds database row-level security, so
application and database enforcement cannot disagree.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.exceptions import ForbiddenError
from app.core.security_audit import ACCESS_DENIED, SecurityEvent


class AccessDeniedError(ForbiddenError):
    """403 that carries the audit event the error handler must record (``access.denied``)."""

    def __init__(self, event: SecurityEvent) -> None:
        super().__init__(code="forbidden")
        self.security_event = event


@dataclass(frozen=True, slots=True)
class SessionState:
    """What the store knows about a presented session after registering it."""

    is_new: bool
    revoked: bool


FirstSeen = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AccessUser:
    """The local identity behind a validated token."""

    id: uuid.UUID
    status: str
    revoked_before: datetime | None = None

    @property
    def is_disabled(self) -> bool:
        return self.status == "disabled"


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Jurisdictions (with descendants) in which ``user_id`` holds ``permission`` right now."""

    user_id: uuid.UUID
    permission: str
    jurisdictions: frozenset[uuid.UUID]

    def denial(self, jurisdiction_id: uuid.UUID | None = None) -> AccessDeniedError:
        return AccessDeniedError(
            SecurityEvent(
                event_type=ACCESS_DENIED,
                outcome="denied",
                actor_user_id=self.user_id,
                jurisdiction_id=jurisdiction_id,
                permission=self.permission,
            )
        )

    def allows(self, jurisdiction_id: uuid.UUID | None) -> bool:
        """Default deny: a missing or unknown jurisdiction is never allowed."""
        return jurisdiction_id is not None and jurisdiction_id in self.jurisdictions

    def require(self, jurisdiction_id: uuid.UUID | None) -> None:
        if not self.allows(jurisdiction_id):
            raise self.denial(jurisdiction_id)

    def visible(self, jurisdiction_ids: Iterable[uuid.UUID | None]) -> list[uuid.UUID]:
        return [j for j in jurisdiction_ids if j is not None and j in self.jurisdictions]


class AccessStore(Protocol):
    """Reads identity and authorization state. Implementations must fail closed."""

    async def get_or_create_user(self, *, issuer: str, subject: str) -> AccessUser:
        """Return the local user, creating a ``pending_role_assignment`` one on first sight."""
        ...

    async def permitted_jurisdictions(
        self, *, user_id: uuid.UUID, permission: str, at: datetime
    ) -> frozenset[uuid.UUID]:
        """Jurisdictions (assignment jurisdiction and all descendants) granting ``permission``."""
        ...

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
        """Record that ``session_key`` was presented and report whether it is revoked.

        When the session is seen for the first time, ``on_first_seen`` runs before the
        registration is committed; if it raises, the registration is rolled back so the
        next request is again treated as the first (no login is ever left unaudited).
        """
        ...

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
        """Revoke one session (works for a session not yet seen: it is created revoked)."""
        ...

    async def revoke_user_sessions(
        self, *, user_id: uuid.UUID, at: datetime, revoked_by: uuid.UUID, reason: str
    ) -> None:
        """Reject every token for the user issued at or before ``at`` (``revoked_before``)."""
        ...

    async def assignment_jurisdictions(self, *, user_id: uuid.UUID) -> frozenset[uuid.UUID]:
        """Jurisdictions of all the user's non-revoked assignments (administrative scope)."""
        ...
