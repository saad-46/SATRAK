"""Validation service abstraction and result type.

Domain invariants live on entities/value objects; this is for *application-level*
validation (composed rule sets, cross-field checks) that yields a structured
result rather than raising, so callers can collect and present all violations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ValidationViolation:
    field: str
    message: str
    code: str = "invalid"


@dataclass(frozen=True)
class ValidationResult:
    violations: tuple[ValidationViolation, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return len(self.violations) == 0

    def merge(self, other: ValidationResult) -> ValidationResult:
        return ValidationResult(violations=(*self.violations, *other.violations))


@runtime_checkable
class Validator[T](Protocol):
    def validate(self, candidate: T) -> ValidationResult: ...
