"""Domain-layer errors.

These are pure domain concerns — they carry a stable ``code`` and message but
know nothing about HTTP, transports, or persistence. The application/API layer
(:mod:`app.core.errors`) is responsible for translating them into transport
responses (RFC 9457 Problem Details). Keeping them decoupled preserves the
clean-architecture dependency rule: the domain never imports infrastructure.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all domain rule violations.

    Subclasses set a stable ``code`` used for programmatic handling and for
    mapping to transport errors at the boundary.
    """

    code: str = "domain_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class InvariantViolation(DomainError):
    """An entity/aggregate was asked to enter an inconsistent state."""

    code = "invariant_violation"


class ValueValidationError(DomainError):
    """A value object was constructed from invalid input."""

    code = "value_validation_error"

    def __init__(
        self, message: str, *, field: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, details=details)
        self.field = field


class BusinessRuleViolation(DomainError):
    """A higher-level business rule spanning multiple values/entities failed."""

    code = "business_rule_violation"


class ConcurrencyConflict(DomainError):
    """Optimistic-concurrency check failed (stale version)."""

    code = "concurrency_conflict"
