"""Phone number value object (E.164-oriented)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

_E164_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


@dataclass(frozen=True)
class PhoneNumber(ValueObject):
    """A normalized phone number.

    Stored in a compact form (optional leading ``+`` and digits only). Formatting
    for display is a presentation concern handled elsewhere.
    """

    value: str

    def __post_init__(self) -> None:
        # Strip common separators before validating.
        compact = re.sub(r"[\s\-().]", "", self.value.strip())
        if not compact:
            raise ValueValidationError("phone number must not be empty", field="phone")
        if not _E164_RE.match(compact):
            raise ValueValidationError(f"invalid phone number: {self.value!r}", field="phone")
        object.__setattr__(self, "value", compact)

    @property
    def has_country_code(self) -> bool:
        return self.value.startswith("+")

    def __str__(self) -> str:
        return self.value
