"""The authenticated caller, as established from a validated access token."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity proven by a valid token. Carries no permissions.

    Authorization (roles, jurisdictions, grants) is read from local state in later
    stories, never trusted from token claims (ADR-0013 D).
    """

    subject: str
    issuer: str
    issued_at: datetime
    expires_at: datetime
    token_id: str | None = None
    session_id: str | None = None

    @classmethod
    def dev_authentication_disabled(cls) -> Principal:
        """Stand-in used only when authentication is explicitly disabled (dev/test)."""
        now = datetime.now(UTC)
        return cls(
            subject="dev-authentication-disabled",
            issuer="local",
            issued_at=now,
            expires_at=now,
        )
