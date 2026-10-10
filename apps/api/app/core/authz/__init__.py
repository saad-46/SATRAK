"""Authorization primitives: default-deny, jurisdiction-scoped permission checks (ADR-0011/0013).

An :class:`AccessContext` is the single answer to "which jurisdictions may this caller act in
for this permission?". Endpoints filter list results by it and check object access with
:meth:`AccessContext.require`; the same set later feeds database row-level security, so
application and database enforcement cannot disagree.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.exceptions import ForbiddenError


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

    def allows(self, jurisdiction_id: uuid.UUID | None) -> bool:
        """Default deny: a missing or unknown jurisdiction is never allowed."""
        return jurisdiction_id is not None and jurisdiction_id in self.jurisdictions

    def require(self, jurisdiction_id: uuid.UUID | None) -> None:
        if not self.allows(jurisdiction_id):
            raise ForbiddenError(code="forbidden")

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
