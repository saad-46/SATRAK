"""Contact information value object (aggregates email/phone/etc.)."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject
from app.shared.value_objects.email import Email
from app.shared.value_objects.phone_number import PhoneNumber


@dataclass(frozen=True)
class ContactInformation(ValueObject):
    """A bundle of contact channels. At least one channel must be present."""

    email: Email | None = None
    phone: PhoneNumber | None = None
    website: str | None = None

    def __post_init__(self) -> None:
        if self.email is None and self.phone is None and not self.website:
            raise ValueValidationError("contact information requires at least one channel")

    @property
    def is_reachable_electronically(self) -> bool:
        return self.email is not None
