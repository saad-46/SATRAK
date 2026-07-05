"""Email address value object."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

# Pragmatic RFC-5321-ish check: not a full grammar, but rejects obvious garbage
# without the false-negatives a stricter regex causes on valid addresses.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_LENGTH = 254


@dataclass(frozen=True)
class Email(ValueObject):
    """A validated, normalized (lower-cased) email address."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not normalized:
            raise ValueValidationError("email must not be empty", field="email")
        if len(normalized) > _MAX_LENGTH:
            raise ValueValidationError("email exceeds maximum length", field="email")
        if not _EMAIL_RE.match(normalized):
            raise ValueValidationError(f"invalid email address: {self.value!r}", field="email")
        object.__setattr__(self, "value", normalized)

    @property
    def local_part(self) -> str:
        return self.value.split("@", 1)[0]

    @property
    def domain(self) -> str:
        return self.value.split("@", 1)[1]

    def __str__(self) -> str:
        return self.value
