"""Postal address value object."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class Address(ValueObject):
    """A structured postal address.

    ``country_code`` is an ISO 3166-1 alpha-2 code (e.g. ``IN``). Region/state and
    postal code are optional to accommodate international variation, but city and
    country are required for an address to be meaningful.
    """

    line1: str
    city: str
    country_code: str
    line2: str | None = None
    region: str | None = None
    postal_code: str | None = None

    def __post_init__(self) -> None:
        if not self.line1.strip():
            raise ValueValidationError("address line1 is required", field="line1")
        if not self.city.strip():
            raise ValueValidationError("city is required", field="city")
        code = self.country_code.strip().upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueValidationError(
                "country_code must be an ISO 3166-1 alpha-2 code", field="country_code"
            )
        object.__setattr__(self, "country_code", code)

    def as_single_line(self) -> str:
        parts = [
            self.line1,
            self.line2,
            self.city,
            self.region,
            self.postal_code,
            self.country_code,
        ]
        return ", ".join(p.strip() for p in parts if p and p.strip())
