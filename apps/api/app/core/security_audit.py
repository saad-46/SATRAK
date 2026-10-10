"""Security audit log: durable, append-only, hash-chained record of security decisions.

Distinct from the domain audit port in ``app.shared.services.audit`` (which records business
actions on aggregates): these events describe authentication and authorization outcomes
(``user.logged_in``, ``user.login_failed``, ``access.denied``, ``session.revoked``).

Each event stores the hash of its predecessor, so removing, reordering or editing any row
breaks the chain and :meth:`SecurityAuditLog.verify_chain` reports the first broken position.
Events never carry tokens, credentials or free-form user input: ``details`` accepts only
short scalar values and rejects secret-looking keys.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol

GENESIS_HASH: Final = "0" * 64

USER_LOGGED_IN: Final = "user.logged_in"
USER_LOGIN_FAILED: Final = "user.login_failed"
ACCESS_DENIED: Final = "access.denied"
SESSION_REVOKED: Final = "session.revoked"
EVENT_TYPES: Final = frozenset({USER_LOGGED_IN, USER_LOGIN_FAILED, ACCESS_DENIED, SESSION_REVOKED})
OUTCOMES: Final = frozenset({"success", "failure", "denied"})

_FORBIDDEN_KEY_PARTS = ("token", "authorization", "password", "secret", "credential", "cookie")
_MAX_VALUE_LENGTH = 200

Scalar = str | int | bool | None


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    event_type: str
    outcome: str
    actor_user_id: uuid.UUID | None = None
    jurisdiction_id: uuid.UUID | None = None
    permission: str | None = None
    ip: str | None = None
    request_id: str | None = None
    details: Mapping[str, Scalar] = field(default_factory=dict)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown security event type: {self.event_type!r}")
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown security event outcome: {self.outcome!r}")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        for key, value in self.details.items():
            if any(part in key.lower() for part in _FORBIDDEN_KEY_PARTS):
                raise ValueError(f"audit detail key {key!r} may carry a secret")
            if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
                raise ValueError(f"audit detail {key!r} is too long")
            if not isinstance(value, str | int | bool | None):
                raise ValueError(f"audit detail {key!r} must be a scalar")


def canonical_fields(event: SecurityEvent) -> str:
    """Deterministic serialization of everything the hash covers."""
    return json.dumps(
        {
            "id": str(event.id),
            "occurred_at": event.occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
            "event_type": event.event_type,
            "outcome": event.outcome,
            "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
            "jurisdiction_id": str(event.jurisdiction_id) if event.jurisdiction_id else None,
            "permission": event.permission,
            "ip": event.ip,
            "request_id": event.request_id,
            "details": dict(event.details),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def chain_hash(previous_hash: str, event: SecurityEvent) -> str:
    return hashlib.sha256(f"{previous_hash}\n{canonical_fields(event)}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainReport:
    ok: bool
    checked: int
    first_bad_position: int | None = None
    reason: str | None = None


class SecurityAuditLog(Protocol):
    async def record(self, event: SecurityEvent) -> None:
        """Durably append ``event``. Raises on failure; callers decide how to fail closed."""
        ...

    async def verify_chain(self) -> ChainReport:
        """Recompute every hash in order; report the first position that does not match."""
        ...


@dataclass
class InMemorySecurityAuditLog:
    """Reference implementation with the same chain semantics (tests, local development)."""

    events: list[SecurityEvent] = field(default_factory=list)
    hashes: list[tuple[str, str]] = field(default_factory=list)  # (prev_hash, hash)
    fail: bool = False  # tests flip this to simulate an audit-store outage

    async def record(self, event: SecurityEvent) -> None:
        if self.fail:
            raise RuntimeError("audit store unavailable")
        previous = self.hashes[-1][1] if self.hashes else GENESIS_HASH
        self.events.append(event)
        self.hashes.append((previous, chain_hash(previous, event)))

    async def verify_chain(self) -> ChainReport:
        previous = GENESIS_HASH
        for position, (event, (stored_prev, stored_hash)) in enumerate(
            zip(self.events, self.hashes, strict=True), start=1
        ):
            if stored_prev != previous:
                return ChainReport(False, position - 1, position, "broken link")
            if chain_hash(previous, event) != stored_hash:
                return ChainReport(False, position - 1, position, "hash mismatch")
            previous = stored_hash
        return ChainReport(True, len(self.events))

    def of_type(self, event_type: str) -> list[SecurityEvent]:
        return [e for e in self.events if e.event_type == event_type]
